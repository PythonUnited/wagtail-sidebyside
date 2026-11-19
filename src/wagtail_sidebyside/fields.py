"""Which parts of a page or snippet are translatable, and how to write
translations back.

An object is flattened into units: one per translatable text (model field or
StreamField leaf block), keyed by a stable path such as "title" or
"body.<block-id>.caption", plus one per image or document, which follows the
source unless the translation picks its own. Everything else (choices, plugin
config, ...) is copied from the source when a translation is saved.

Fields listed in a model's `translation_exclude` always come from the source,
e.g. translation_exclude = ["header_image"].
"""

import difflib
import functools
from dataclasses import dataclass

from django.db import models
from django.utils.text import capfirst
from django.utils.translation import gettext as _
from wagtail import blocks, hooks
from wagtail.contrib.typed_table_block.blocks import BaseTypedTableBlock
from wagtail.documents import get_document_model
from wagtail.documents.blocks import DocumentChooserBlock
from wagtail.fields import RichTextField, StreamField
from wagtail.images import get_image_model
from wagtail.images.blocks import ImageChooserBlock
from wagtail.models import Page

from . import objects

TEXT = "text"
TEXTAREA = "textarea"
RICHTEXT = "richtext"
HTML = "html"
TEXT_KINDS = {TEXT, TEXTAREA, RICHTEXT, HTML}
# An image or document (value: its id), the source's unless overridden.
IMAGE = "image"
DOCUMENT = "document"
CHOOSER_KINDS = {IMAGE, DOCUMENT}
# Marker for a block without translatable text, shown as a grey row.
SYNCED = "synced"

# Page fields that are translated; always shown, even when empty in the source
# (so is every field of the metadata section), as the translation may fill them.
PAGE_FIELDS = ["title", "slug", "seo_title", "search_description"]
# Page fields copied from the source. Other Page fields are tree, workflow or
# publishing state that belongs to the translated page itself.
SYNCED_PAGE_FIELDS = ["show_in_menus"]


# Sections of the translation screen: the editor's first tab, and the rest
# (slug, search engine fields: Wagtail's "Promote" tab).
CONTENT = "content"
METADATA = "metadata"


@dataclass
class Unit:
    path: str
    label: str
    kind: str
    source: str
    features: list[str] | None = None
    section: str = CONTENT


def page_units(obj, align_to=None) -> list[Unit]:
    """Units of a page or snippet. With align_to, StreamField blocks get the
    paths of the matching blocks in align_to (see _align)."""
    units = []
    tabs = _panel_tabs(type(obj))
    for field in _translatable_fields(obj):
        value = getattr(obj, field.name)
        label = capfirst(field.verbose_name)
        count = len(units)
        if isinstance(field, StreamField):
            raw = _raw(field, value)
            if align_to is not None:
                raw = _align(
                    field.stream_block, _raw(field, getattr(align_to, field.name)), raw
                )
            _walk(field.stream_block, raw, field.name, label, units, {})
        elif isinstance(field, models.ForeignKey):
            object_id = getattr(obj, field.attname)
            units.append(
                Unit(field.name, label, _field_kind(field), str(object_id or ""))
            )
        elif (
            value
            or (objects.is_page(obj) and field.name in PAGE_FIELDS)
            or tabs.get(field.name, 0) > 0
        ):
            units.append(
                Unit(
                    field.name,
                    label,
                    _field_kind(field),
                    value or "",
                    getattr(field, "features", None),
                )
            )
        if tabs.get(field.name, 0) > 0:
            for unit in units[count:]:
                unit.section = METADATA
    return units


def page_texts(obj, align_to=None) -> dict[str, str]:
    """path -> value of every unit: texts, and image/document ids."""
    return {
        unit.path: unit.source
        for unit in page_units(obj, align_to)
        if unit.kind != SYNCED
    }


def apply_translations(source, target, values: dict[str, str]):
    """Make target a copy of source, with values (path -> text) replacing the
    source text of translated units. Untranslated units keep the source text."""
    translatable = {field.name for field in _translatable_fields(source)}
    for field in _content_fields(source):
        if field.name not in translatable:
            setattr(target, field.attname, getattr(source, field.attname))
        elif isinstance(field, StreamField):
            raw = _walk(
                field.stream_block,
                _raw(field, getattr(source, field.name)),
                field.name,
                "",
                [],
                values,
            )
            setattr(target, field.name, field.stream_block.to_python(raw))
        elif isinstance(field, models.ForeignKey):
            value = values.get(field.name)
            setattr(
                target,
                field.attname,
                int(value) if value else getattr(source, field.attname),
            )
        elif field.name == "slug" and "slug" not in values:
            # An untranslated slug follows the source slug, unless a sibling
            # already has it (e.g. site roots, which share a parent).
            siblings = target.get_parent().get_children().exclude(pk=target.pk)
            if not siblings.filter(slug=source.slug).exists():
                target.slug = source.slug
        else:
            setattr(
                target, field.name, values.get(field.name, getattr(source, field.name))
            )
    return target


def _content_fields(obj):
    """A page: the Page fields above plus all fields of the specific page
    model. A snippet: its fields, without the state of Wagtail's mixins."""
    if objects.is_page(obj):
        names = PAGE_FIELDS + SYNCED_PAGE_FIELDS
        yield from (obj._meta.get_field(name) for name in names)
    for field in obj._meta.concrete_fields:
        if field.primary_key or field.model is Page:
            continue
        if objects.is_page(obj) or field.name not in objects.MIXIN_FIELDS:
            yield field


def _translatable_fields(obj):
    """Translatable fields in the order of the editor's panels (fields
    without a panel last)."""
    exclude = set(getattr(obj, "translation_exclude", []))
    order = _panel_order(type(obj))
    fields = [
        field
        for field in _content_fields(obj)
        if (objects.is_page(obj) and field.name in PAGE_FIELDS)
        or (field.name not in exclude and _is_translatable(field))
    ]
    return sorted(fields, key=lambda field: order.get(field.name, len(order)))


@functools.cache
def _panel_order(model) -> dict[str, int]:
    """Field name -> position in the editor (tabs and panels in order)."""
    names = [name for tab in _editor_tabs(model) for name in tab]
    return {name: index for index, name in enumerate(names)}


@functools.cache
def _panel_tabs(model) -> dict[str, int]:
    """Field name -> index of its tab in the editor."""
    return {
        name: index for index, tab in enumerate(_editor_tabs(model)) for name in tab
    }


def _editor_tabs(model) -> list[list[str]]:
    """Field names per tab of the editor, in order."""

    def walk(panel):
        if getattr(panel, "field_name", None):
            yield panel.field_name
        for child in getattr(panel, "children", []):
            yield from walk(child)

    return [list(walk(tab)) for tab in objects.editor_tabs(model)]


def _is_translatable(field) -> bool:
    if isinstance(field, (StreamField, RichTextField)):
        return True
    if isinstance(field, models.ForeignKey):
        return field.related_model in (get_image_model(), get_document_model())
    if field.choices or isinstance(field, (models.EmailField, models.URLField)):
        return False
    return isinstance(field, (models.CharField, models.TextField))


def _field_kind(field) -> str:
    if isinstance(field, models.ForeignKey):
        return IMAGE if field.related_model is get_image_model() else DOCUMENT
    if isinstance(field, RichTextField):
        return RICHTEXT
    if isinstance(field, models.TextField):
        return TEXTAREA
    return TEXT


def _block_kind(block) -> str | None:
    """What a leaf block is for the translation screen: a text kind, IMAGE,
    DOCUMENT, or None (copied from the source). Projects decide for their own
    blocks with the "sidebyside_block_kind" hook: return a kind, False (not
    translatable) or None (let the next hook or the default decide)."""
    for fn in hooks.get_hooks("sidebyside_block_kind"):
        kind = fn(block)
        if kind is not None:
            return kind or None
    if isinstance(block, ImageChooserBlock):
        return IMAGE
    if isinstance(block, DocumentChooserBlock):
        return DOCUMENT
    if isinstance(block, blocks.RichTextBlock):
        return RICHTEXT
    if isinstance(block, blocks.RawHTMLBlock):
        return HTML
    if isinstance(block, blocks.TextBlock):
        return TEXTAREA
    if isinstance(block, blocks.CharBlock):
        return TEXT
    return None


def _raw(field: StreamField, value) -> list:
    return field.stream_block.get_prep_value(value)


def _walk(block, raw, path: str, label: str, units: list, values: dict):
    """Walk raw (JSON) block data next to its block definition. Collects a Unit
    per translatable leaf and returns the raw data with leaves replaced by
    values[path] where given."""
    if isinstance(block, blocks.StreamBlock):
        result = []
        for child in raw:
            child_block = block.child_blocks.get(child["type"])
            if child_block is None:
                result.append(child)
                continue
            child_path = f"{path}.{child['id']}"
            child_label = f"{label} > {child_block.label}"
            count = len(units)
            value = _walk(
                child_block, child["value"], child_path, child_label, units, values
            )
            if len(units) == count:
                units.append(Unit(child_path, child_label, SYNCED, ""))
            result.append({**child, "value": value})
        return result

    if isinstance(block, blocks.ListBlock):
        result = []
        for index, item in enumerate(raw):
            item_label = f"{label} {index + 1}"
            if isinstance(item, dict) and item.get("type") == "item" and "id" in item:
                value = _walk(
                    block.child_block,
                    item["value"],
                    f"{path}.{item['id']}",
                    item_label,
                    units,
                    values,
                )
                result.append({**item, "value": value})
            else:
                # Legacy list format without item ids.
                result.append(
                    _walk(
                        block.child_block,
                        item,
                        f"{path}.{index}",
                        item_label,
                        units,
                        values,
                    )
                )
        return result

    if isinstance(block, blocks.StructBlock):
        return {
            name: _walk(
                block.child_blocks[name],
                value,
                f"{path}.{name}",
                f"{label} > {block.child_blocks[name].label}",
                units,
                values,
            )
            if name in block.child_blocks
            else value
            for name, value in raw.items()
        }

    if isinstance(block, BaseTypedTableBlock):
        return _walk_table(block, raw or {}, path, label, units, values)

    return _leaf(
        _block_kind(block),
        raw,
        path,
        label,
        units,
        values,
        getattr(block, "features", None),
    )


def _leaf(kind, raw, path: str, label: str, units: list, values: dict, features=None):
    """Collect a Unit for a translatable leaf value and return it, replaced by
    values[path] where given."""
    if kind in CHOOSER_KINDS:
        units.append(Unit(path, label, kind, "" if raw is None else str(raw)))
        return int(values[path]) if values.get(path) else raw
    if kind is None or not isinstance(raw, str) or not raw.strip():
        return raw
    units.append(Unit(path, label, kind, raw, features))
    return values.get(path, raw)


def _walk_table(block, raw: dict, path: str, label: str, units: list, values: dict):
    """A typed table (wagtail.contrib.typed_table_block): the column headings,
    the cells and the caption. Rows and columns have no ids, so their paths
    are positions: a row inserted in the source shifts the cells after it,
    which then show up as outdated (their source text changed)."""
    columns = raw.get("columns") or []
    column_label, row_label, caption_label = _("Column"), _("Row"), _("Caption")
    headings = []
    result_columns = []
    for index, column_data in enumerate(columns):
        headings.append(column_data.get("heading") or f"{column_label} {index + 1}")
        heading = _leaf(
            TEXT,
            column_data.get("heading") or "",
            f"{path}.columns.{index}",
            f"{label} > {headings[index]}",
            units,
            values,
        )
        result_columns.append({**column_data, "heading": heading})

    result_rows = []
    for row_index, row in enumerate(raw.get("rows") or []):
        cells = []
        for index, value in enumerate(row.get("values") or []):
            child_block = (
                block.child_blocks.get(columns[index]["type"])
                if index < len(columns)
                else None
            )
            if child_block is None:
                cells.append(value)
                continue
            cells.append(
                _walk(
                    child_block,
                    value,
                    f"{path}.rows.{row_index}.{index}",
                    f"{label} > {row_label} {row_index + 1} > {headings[index]}",
                    units,
                    values,
                )
            )
        result_rows.append({**row, "values": cells})

    caption = _leaf(
        TEXT,
        raw.get("caption") or "",
        f"{path}.caption",
        f"{label} > {caption_label}",
        units,
        values,
    )
    return {**raw, "columns": result_columns, "rows": result_rows, "caption": caption}


def _align(block, source, target):
    """target raw data with block ids taken from source. Blocks are matched by
    id, the rest by the longest matching sequences of block types (so moved or
    inserted blocks do not shift everything after them). Translations normally
    share block ids with their source (copy_for_translation keeps them), but
    pages created per locale, e.g. by a fixture loader, have their own ids."""
    if isinstance(block, (blocks.StreamBlock, blocks.ListBlock)):
        if not all(isinstance(item, dict) and "id" in item for item in source + target):
            return target  # legacy list format, matched by position anyway
        source_by_id = {item["id"]: item for item in source}
        matches = {
            index: source_by_id[item["id"]]
            for index, item in enumerate(target)
            if item["id"] in source_by_id
            and source_by_id[item["id"]]["type"] == item["type"]
        }
        target_ids = {item["id"] for item in target}
        rest_source = [item for item in source if item["id"] not in target_ids]

        def is_text(item) -> bool:
            child = _child_block(block, item)
            return child is not None and _block_kind(child) in TEXT_KINDS

        # Matching on type alone is ambiguous when blocks moved. Try all
        # blocks in one sequence, and text blocks (heading, paragraph, ...)
        # separately from the rest; keep whichever matches more text blocks,
        # as the text is what must not get lost.
        candidates = [
            _pair(rest_source, target, matches, lambda item: True),
            _pair(rest_source, target, matches, is_text),
        ]
        matches = max(
            candidates,
            key=lambda pairs: sum(is_text(target[index]) for index in pairs),
        )

        result = []
        for index, item in enumerate(target):
            match = matches.get(index)
            if match is None:
                result.append(item)
                continue
            child_block = _child_block(block, item)
            value = (
                _align(child_block, match["value"], item["value"])
                if child_block
                else item["value"]
            )
            result.append({**item, "id": match["id"], "value": value})
        return result

    if isinstance(block, blocks.StructBlock) and isinstance(source, dict):
        return {
            name: _align(block.child_blocks[name], source[name], value)
            if name in block.child_blocks and name in source
            else value
            for name, value in target.items()
        }

    return target


def _child_block(block, item):
    if isinstance(block, blocks.ListBlock):
        return block.child_block
    return block.child_blocks.get(item["type"])


def _pair(source: list, target: list, matches: dict, group) -> dict:
    """matches (target index -> source item) extended by the longest matching
    sequences of block types, per group (items with the same group(item))."""
    matches = dict(matches)
    for value in {group(item) for item in target}:
        rest_target = [
            index
            for index in range(len(target))
            if index not in matches and group(target[index]) == value
        ]
        rest_source = [item for item in source if group(item) == value]
        matcher = difflib.SequenceMatcher(
            None,
            [item["type"] for item in rest_source],
            [target[index]["type"] for index in rest_target],
            autojunk=False,
        )
        for a, b, size in matcher.get_matching_blocks():
            for offset in range(size):
                matches[rest_target[b + offset]] = rest_source[a + offset]
    return matches
