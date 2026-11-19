import difflib
import html
import json
import re
from dataclasses import dataclass

from django.db import transaction
from django.utils.html import strip_tags
from wagtail import hooks
from wagtail.models import RevisionMixin

from .. import objects
from ..conf import source_locale
from ..fields import (
    CHOOSER_KINDS,
    RICHTEXT,
    SYNCED,
    TEXT_KINDS,
    Unit,
    apply_translations,
    page_texts,
    page_units,
)
from ..models import TranslationState

TODO = "todo"
DONE = "done"
OUTDATED = "outdated"
# Machine translated, not yet checked by an editor.
REVIEW = "review"


@dataclass
class Row:
    unit: Unit
    status: str
    translation: str = ""
    diff: list[tuple[str, str]] | None = None
    # "Same in both languages": always shows the (current) source text.
    same: bool = False
    # Image or document: the translation has its own instead of the source's.
    override: bool = False
    # Filled in from a removed block with the same source text (to review).
    reused: bool = False


class TranslatePage:
    @staticmethod
    def source_of(obj):
        """The page or snippet in the source locale obj is a translation of,
        or None if obj is itself a source or has no source."""
        locale = source_locale()
        if obj.locale_id == locale.id:
            return None
        return obj.get_translation_or_none(locale)

    @staticmethod
    def rows(source, target) -> list[Row]:
        """One row per source unit with its translation status. source and
        target are the latest versions (objects.latest) of the (specific)
        pages or snippets."""
        units = page_units(source)
        translations = page_texts(target, align_to=source)
        entries = TranslatePage._entries(units, translations, source, target)
        reusable = TranslatePage._reusable(target)

        rows = []
        for unit in units:
            entry = entries.get(unit.path)
            translation = translations.get(unit.path, "")
            if unit.kind == SYNCED:
                rows.append(Row(unit, DONE))
            elif unit.kind in CHOOSER_KINDS:
                override = entry is not None and entry.get("override", False)
                rows.append(
                    Row(unit, DONE, translation if override else "", override=override)
                )
            elif entry is not None and entry.get("same"):
                rows.append(Row(unit, DONE, entry.get("text", ""), same=True))
            elif (entry is None or not translation) and _normalise(
                unit.source
            ) in reusable:
                text = reusable[_normalise(unit.source)]["text"]
                rows.append(Row(unit, REVIEW, text, reused=True))
            elif not unit.source and not translation:
                # Empty in the source (e.g. a meta description): nothing to
                # translate, but the translation may fill it.
                rows.append(Row(unit, DONE))
            elif entry is None or not translation:
                rows.append(Row(unit, TODO))
            elif entry["source"] != unit.source:
                diff = TranslatePage.word_diff(
                    TranslatePage._plain(unit, entry["source"]),
                    TranslatePage._plain(unit, unit.source),
                )
                rows.append(Row(unit, OUTDATED, translation, diff))
            elif entry.get("machine"):
                rows.append(Row(unit, REVIEW, translation))
            else:
                rows.append(Row(unit, DONE, translation))
        # Projects can drop or change rows, e.g. leave a field out.
        for fn in hooks.get_hooks("sidebyside_construct_rows"):
            fn(rows, source, target)
        return rows

    @staticmethod
    def save(
        source,
        target,
        rows: list[Row],
        values: dict[str, str],
        changed: set[str],
        confirmed: set[str],
        machine: set[str],
        user,
        publish: bool,
        same: frozenset[str] = frozenset(),
        copied: frozenset[str] = frozenset(),
        live_source=None,
        awaiting_source: bool = False,
    ):
        """Save target as a new version of source with the given translations
        (see objects.save). Returns the revision, None for a snippet without
        revisions.

        A translation is never ahead of its source. With publish and
        live_source (the published version of a source that has a newer
        draft), the published revision is built from live_source and the
        source's draft only goes into a new draft revision, which is published
        along when the source is (awaiting_source). awaiting_source without
        publish: the same, for "publish source and translation" (the source is
        published right after this).

        values: path -> translated text, empty = untranslated (source text is
        used). A unit is recorded as translated from the current source text
        when its text changed or the editor confirmed it (outdated or
        machine translated); otherwise it keeps its earlier state (so outdated
        stays outdated). machine: paths holding an unchanged machine translation
        (or a reused one, see removed()).
        An image or document with a value is the translation's own (override).
        same: paths marked "Same in both languages"; they take the current
        source text, now and after every change of the source. Text typed in
        such a field is kept aside, for when the editor unticks it again.
        copied: paths holding a copied source text, unchanged: not translated.
        """
        entries = TranslatePage._entries(
            [row.unit for row in rows],
            page_texts(target, align_to=source),
            source,
            target,
        )
        translations = TranslatePage.translations(rows, values, same, copied)
        new_entries = {}
        for row in rows:
            path = row.unit.path
            if row.unit.kind in CHOOSER_KINDS:
                if path in translations:
                    new_entries[path] = {"source": row.unit.source, "override": True}
            elif path in same:
                new_entries[path] = {"source": row.unit.source, "same": True}
                if values.get(path):
                    new_entries[path]["text"] = values[path]
            elif path not in translations:
                continue
            elif path in confirmed:
                new_entries[path] = {"source": row.unit.source}
            elif path in changed or path not in entries or entries[path].get("same"):
                new_entries[path] = {"source": row.unit.source}
                if path in machine or (row.reused and path not in changed):
                    new_entries[path]["machine"] = True
            else:
                new_entries[path] = entries[path]

        removed = TranslatePage._update_removed(
            source, target, rows, entries, translations
        )
        with transaction.atomic():
            if publish and live_source is not None:
                apply_translations(live_source, target, translations)
                objects.save(target, user, publish=True)
                objects.reload_state(target)
                awaiting_source = True
                publish = False
            apply_translations(source, target, translations)
            revision = objects.save(target, user, publish)
            TranslationState.objects.store(
                target, new_entries, removed, awaiting_source
            )
        return revision

    @staticmethod
    def translations(
        rows: list[Row], values: dict[str, str], same, copied=frozenset()
    ) -> dict[str, str]:
        """path -> text (or image/document id) to put in the page. Left out
        (so the source's is used): empty fields, "Same in both languages", and
        a copied source text saved unchanged, which is not a translation. A
        text equal to the source that was typed or machine translated (e.g. a
        name) is a translation."""
        return {
            row.unit.path: values[row.unit.path]
            for row in rows
            if row.unit.kind != SYNCED
            and row.unit.path not in same
            and row.unit.path not in copied
            and values.get(row.unit.path)
        }

    @staticmethod
    def preview(source, target, rows: list[Row], values, same):
        """target with the given translations applied, not saved."""
        return apply_translations(
            source, target, TranslatePage.translations(rows, values, same)
        )

    @staticmethod
    def removed(target) -> list[dict]:
        """Translated texts whose block was removed from the source."""
        state = TranslationState.objects.for_object(target)
        return state.removed if state else []

    @staticmethod
    def discard_removed(target, index: int):
        state = TranslationState.objects.for_object(target)
        if state and 0 <= index < len(state.removed):
            del state.removed[index]
            state.save(update_fields=["removed", "updated_at"])

    @staticmethod
    def _reusable(target) -> dict[str, dict]:
        """Removed translations by their (normalised) source text: a block
        with that source text again (put back, cut and pasted) gets it."""
        return {
            _normalise(item["source"]): item
            for item in TranslatePage.removed(target)
            if item.get("source")
        }

    @staticmethod
    def _update_removed(source, target, rows, entries, translations) -> list[dict]:
        """The removed list after this save: plus the texts that are about to
        disappear because their block left the source, minus reused ones."""
        removed = list(TranslatePage.removed(target))
        for unit in TranslatePage.orphans(source, target):
            item = {
                "label": unit.label,
                "kind": unit.kind,
                "source": entries.get(unit.path, {}).get("source", ""),
                "text": unit.source,
            }
            if item not in removed:
                removed.append(item)
        reused = {
            _normalise(row.unit.source)
            for row in rows
            if row.reused and row.unit.path in translations
        }
        return [item for item in removed if _normalise(item["source"]) not in reused]

    @staticmethod
    def orphans(source, target) -> list[Unit]:
        """Texts of target without a counterpart in source (blocks the source
        no longer has, or of another type). Saving the translation removes
        them, so they are shown to the editor and block automatic publishing."""
        source_paths = {unit.path for unit in page_units(source)}
        return [
            unit
            for unit in page_units(target, align_to=source)
            if unit.kind in TEXT_KINDS and unit.path not in source_paths
        ]

    @staticmethod
    def progress(rows: list[Row]) -> tuple[int, int]:
        texts = [row for row in rows if row.unit.kind in TEXT_KINDS]
        return sum(row.status == DONE for row in texts), len(texts)

    @staticmethod
    def word_diff(old: str, new: str) -> list[tuple[str, str]]:
        """Word level diff as (op, text) pairs, op being equal, delete or insert."""
        old_words = re.findall(r"\S+|\s+", old)
        new_words = re.findall(r"\S+|\s+", new)
        diff = []
        matcher = difflib.SequenceMatcher(None, old_words, new_words, autojunk=False)
        for op, i1, i2, j1, j2 in matcher.get_opcodes():
            if op == "equal":
                diff.append(("equal", "".join(old_words[i1:i2])))
                continue
            if i2 > i1:
                diff.append(("delete", "".join(old_words[i1:i2])))
            if j2 > j1:
                diff.append(("insert", "".join(new_words[j1:j2])))
        return diff

    @staticmethod
    def _entries(
        units: list[Unit], translations: dict[str, str], source, target
    ) -> dict:
        """Stored entries, or for a page translated before this app existed
        (e.g. with wagtail-localize) a baseline: a unit counts as translated
        from the current source if its text looks like a translation."""
        state = TranslationState.objects.for_object(target)
        if state is not None:
            return state.entries
        history = TranslatePage._source_history(source)
        entries = {}
        for unit in units:
            value = translations.get(unit.path)
            if unit.kind in CHOOSER_KINDS:
                # An image or document of its own is kept as an override.
                if value and value != unit.source:
                    entries[unit.path] = {"source": unit.source, "override": True}
            elif unit.kind in TEXT_KINDS and TranslatePage._looks_translated(
                unit, value, history
            ):
                entries[unit.path] = {"source": unit.source}
        return entries

    @staticmethod
    def _looks_translated(unit: Unit, text: str | None, history: set[str]) -> bool:
        """Heuristic for the baseline only. Not a translation: no text, a text
        the source page has (or had in an earlier revision), or a stub much
        shorter than the source (e.g. "/")."""
        plain = _normalise(text or "")
        if not plain or plain in history or plain == _normalise(unit.source):
            return False
        source_words = len(_normalise(unit.source).split())
        return not (source_words >= 5 and len(plain.split()) < source_words / 4)

    @staticmethod
    def _source_history(source) -> set[str]:
        """All texts in the last revisions of the source, normalised. A
        snippet without revisions has no history."""
        texts = set()
        if not isinstance(source, RevisionMixin):
            return texts

        def collect(value):
            if isinstance(value, dict):
                for item in value.values():
                    collect(item)
            elif isinstance(value, list):
                for item in value:
                    collect(item)
            elif isinstance(value, str):
                if value.startswith("["):  # StreamField stored as JSON text
                    try:
                        collect(json.loads(value))
                        return
                    except ValueError:
                        pass
                texts.add(_normalise(value))

        for content in source.revisions.order_by("-created_at").values_list(
            "content", flat=True
        )[:100]:
            collect(content)
        return texts

    @staticmethod
    def _plain(unit: Unit, text: str) -> str:
        return strip_tags(text) if unit.kind == RICHTEXT else text


def _normalise(text: str) -> str:
    return " ".join(html.unescape(strip_tags(text)).split())
