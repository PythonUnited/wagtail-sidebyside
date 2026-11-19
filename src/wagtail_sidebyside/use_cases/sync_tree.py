import logging

from django.core.exceptions import ValidationError
from wagtail.models import Locale, Page

from .. import objects
from ..conf import source_locale
from ..models import TranslationState
from .translate_page import TranslatePage

logger = logging.getLogger(__name__)


class SyncTree:
    """Keep the translations in step with their source: the translation trees
    with the source tree, translated snippets with their source snippet."""

    @staticmethod
    def is_source(obj) -> bool:
        if objects.is_page(obj) and obj.is_root():
            return False
        return obj.locale_id == source_locale().id

    @staticmethod
    def create_translations(obj, user=None) -> list:
        """Create the missing translations of a source page or snippet. They
        show the source text until translated, so they go live if the source
        is live."""
        created = []
        for locale in Locale.objects.exclude(pk=obj.locale_id):
            if obj.has_translation(locale):
                continue
            if objects.is_page(obj):
                translation = obj.copy_for_translation(
                    locale, copy_parents=True
                ).specific
            else:
                translation = SyncTree._copy_snippet(obj, locale, user)
            # Nothing translated yet. Without a state the object would get the
            # baseline for pre-existing translations, which takes any text that
            # differs from the source for a translation (with autosave the copy
            # can hold an earlier version of the source, e.g. a half typed title).
            TranslationState.objects.store(translation, {})
            if objects.is_page(obj) and obj.live:
                objects.save(translation, user, publish=True)
            created.append(translation)
        return created

    @staticmethod
    def _copy_snippet(source, locale, user):
        translation = source.copy_for_translation(locale)
        if objects.has_drafts(translation):
            # Not the source's publishing history: published below, or not.
            translation.live_revision = None
            translation.first_published_at = translation.last_published_at = None
        return objects.create(translation, user, publish=objects.is_live(source))

    @staticmethod
    def propagate(source, user=None):
        """Rebuild every translation from the just published (or, without
        drafts, saved) source: new images, plugin settings and untranslated
        text follow the source, translations stay. A translation is published
        along, unless it has a pending draft of its own, was unpublished on
        purpose or has texts that would be lost (see TranslatePage.orphans);
        then only its draft is rebuilt. A draft that only waited for this
        source (awaiting_source) is published."""
        for target_object in source.get_translations():
            target_object = objects.specific(target_object)
            target = objects.latest(target_object)
            rows = TranslatePage.rows(source, target)
            values = {row.unit.path: row.translation for row in rows if row.translation}
            state = TranslationState.objects.for_object(target_object)
            publish = (
                objects.never_published(target_object)
                or (
                    objects.is_live(target_object)
                    and not objects.has_unpublished_changes(target_object)
                )
                or (state is not None and state.awaiting_source)
            ) and not TranslatePage.orphans(source, target)
            try:
                TranslatePage.save(
                    source,
                    target,
                    rows,
                    values,
                    set(),
                    set(),
                    set(),
                    user,
                    publish,
                    same=frozenset(row.unit.path for row in rows if row.same),
                )
            except ValidationError:
                # E.g. a slug clash. Must not block publishing the source; the
                # translation shows up as outdated and is fixed by hand.
                logger.exception("Could not update translation %s", target_object.pk)

    @staticmethod
    def fixed_translations(items) -> list[tuple]:
        """(translation, source) for the translations in items (pages, or
        snippets of one model) that may not be moved or deleted on their own:
        they follow their source. A translation whose source is in items too
        goes along with it."""
        ids = {item.pk for item in items}
        fixed = []
        for item in items:
            if SyncTree.is_source(item) or (objects.is_page(item) and item.is_root()):
                continue
            source = item.get_translation_or_none(source_locale())
            if source is not None and source.pk not in ids:
                fixed.append((item, source))
        return fixed

    @staticmethod
    def delete_translations(source):
        """A deleted source snippet takes its translations along (pages:
        Wagtail's cascade, see cascade())."""
        for translation in source.get_translations():
            translation.delete()

    @staticmethod
    def cascade(pages: list[Page]) -> dict:
        """Translations that follow a source page when it is moved, deleted or
        unpublished (Wagtail's construct_translated_pages_to_cascade_actions)."""
        return {
            page: page.get_translations() for page in pages if SyncTree.is_source(page)
        }
