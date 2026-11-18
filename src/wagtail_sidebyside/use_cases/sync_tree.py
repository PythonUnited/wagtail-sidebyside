import logging

from django.core.exceptions import ValidationError
from wagtail.models import Locale, Page

from ..conf import source_locale
from ..models import TranslationState
from .translate_page import TranslatePage

logger = logging.getLogger(__name__)


class SyncTree:
    """Keep the translation trees in step with the source tree."""

    @staticmethod
    def is_source(page: Page) -> bool:
        return not page.is_root() and page.locale_id == source_locale().id

    @staticmethod
    def create_translations(page: Page, user=None) -> list[Page]:
        """Create the missing translations of a source page. They show the
        source text until translated, so they go live if the source is live."""
        created = []
        for locale in Locale.objects.exclude(pk=page.locale_id):
            if page.has_translation(locale):
                continue
            translation = page.copy_for_translation(locale, copy_parents=True).specific
            # Nothing translated yet. Without a state the page would get the
            # baseline for pre-existing translations, which takes any text that
            # differs from the source for a translation (with autosave the copy
            # can hold an earlier version of the source, e.g. a half typed title).
            TranslationState.objects.store(translation, {})
            if page.live:
                translation.save_revision(user=user, log_action=True).publish(user=user)
            created.append(translation)
        return created

    @staticmethod
    def propagate(source: Page, user=None):
        """Rebuild every translation from the just published source: new
        images, plugin settings and untranslated text follow the source,
        translations stay. A translation is published along, unless it has a
        pending draft of its own, was unpublished on purpose or has texts that
        would be lost (see TranslatePage.orphans); then only its draft is
        rebuilt. A draft that only waited for this source (awaiting_source) is
        published."""
        for target_page in source.get_translations():
            target_page = target_page.specific
            target = target_page.get_latest_revision_as_object()
            rows = TranslatePage.rows(source, target)
            values = {row.unit.path: row.translation for row in rows if row.translation}
            state = TranslationState.objects.for_page(target_page)
            publish = (
                target_page.first_published_at is None
                or (target_page.live and not target_page.has_unpublished_changes)
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
                logger.exception("Could not update translation %s", target_page.pk)

    @staticmethod
    def fixed_translations(pages) -> list[tuple[Page, Page]]:
        """(translation, source) for the translations in pages that may not be
        moved or deleted on their own: they follow their source page. A
        translation whose source is in pages too goes along with it."""
        ids = {page.pk for page in pages}
        fixed = []
        for page in pages:
            if SyncTree.is_source(page) or page.is_root():
                continue
            source = page.get_translation_or_none(source_locale())
            if source is not None and source.pk not in ids:
                fixed.append((page, source))
        return fixed

    @staticmethod
    def cascade(pages: list[Page]) -> dict:
        """Translations that follow a source page when it is moved, deleted or
        unpublished (Wagtail's construct_translated_pages_to_cascade_actions)."""
        return {
            page: page.get_translations() for page in pages if SyncTree.is_source(page)
        }
