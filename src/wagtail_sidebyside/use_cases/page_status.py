from dataclasses import dataclass

from django.urls import reverse
from django.utils.translation import gettext as _
from wagtail.models import Locale, Page

from ..conf import source_locale
from ..fields import TEXT_KINDS
from ..models import TranslationState
from .translate_page import DONE, OUTDATED, REVIEW, TODO, TranslatePage

MISSING = "missing"
# Created but nothing translated yet: the page shows the source text.
NOT_STARTED = "not_started"


@dataclass
class Status:
    source: Page
    locale: Locale
    target: Page | None = None
    todo: int = 0
    outdated: int = 0
    review: int = 0
    started: bool = True

    @property
    def state(self) -> str:
        if self.target is None:
            return MISSING
        if not self.started:
            return NOT_STARTED
        if self.outdated:
            return OUTDATED
        if self.todo:
            return TODO
        if self.review:
            return REVIEW
        return DONE

    @property
    def needs_work(self) -> bool:
        return self.state != DONE

    @property
    def label(self) -> str:
        if self.target is None:
            return _("Not created")
        if not self.started:
            return _("Not started")
        parts = []
        if self.outdated:
            parts.append(_("%(count)s outdated") % {"count": self.outdated})
        if self.todo:
            parts.append(_("%(count)s to do") % {"count": self.todo})
        if self.review:
            parts.append(_("%(count)s to review") % {"count": self.review})
        return ", ".join(parts) or _("Translated")

    @property
    def url(self) -> str:
        return reverse(
            "sidebyside:translate", args=[self.source.pk, self.locale.language_code]
        )


class PageStatus:
    @staticmethod
    def target_locales(source: Page):
        return Locale.objects.exclude(pk=source.locale_id)

    @staticmethod
    def for_page(source: Page) -> list[Status]:
        """Translation status of a source page, one per target locale."""
        source = source.specific
        latest = source.get_latest_revision_as_object()
        statuses = []
        for locale in PageStatus.target_locales(source):
            target = source.get_translation_or_none(locale)
            status = Status(source, locale, target)
            if target is not None:
                status.started = PageStatus.started(target)
                rows = TranslatePage.rows(
                    latest, target.specific.get_latest_revision_as_object()
                )
                rows = [row for row in rows if row.unit.kind in TEXT_KINDS]
                status.todo = sum(row.status == TODO for row in rows)
                status.outdated = sum(row.status == OUTDATED for row in rows)
                status.review = sum(row.status == REVIEW for row in rows)
            statuses.append(status)
        return statuses

    @staticmethod
    def started(target: Page) -> bool:
        """Whether anything of translation target was translated. A page that
        was translated before this app was installed has no state: it counts
        as started."""
        state = TranslationState.objects.for_page(target)
        return state is None or any(
            not entry.get("override") for entry in state.entries.values()
        )

    @staticmethod
    def overview(show: str = "all") -> list[tuple[Page, list[Status]]]:
        """All source pages in tree order with their translation statuses.
        show "work": only pages with work in some language; "started": idem,
        but not counting translations that were not started."""
        pages = (
            Page.objects.filter(locale=source_locale(), depth__gt=1)
            .order_by("path")
            .specific()
        )
        result = [(page, PageStatus.for_page(page)) for page in pages]
        if show in ("work", "started"):
            result = [
                (page, statuses)
                for page, statuses in result
                if any(
                    status.needs_work and (show == "work" or status.started)
                    for status in statuses
                )
            ]
        return result


class HeadLinks:
    @staticmethod
    def for_page(page: Page, request=None) -> dict:
        """canonical and hreflang links for a page on the site. A translation
        that was not started shows the source text: its canonical is the
        source page and it is left out of the hreflang alternates."""
        source_id = source_locale().id
        live = Page.objects.filter(
            translation_key=page.translation_key, live=True
        ).select_related("locale")
        versions = [
            version
            for version in live
            if version.locale_id == source_id or PageStatus.started(version)
        ]
        source = next((v for v in versions if v.locale_id == source_id), None)
        if page.locale_id != source_id and not PageStatus.started(page):
            canonical = source.get_full_url(request) if source else None
            return {"canonical": canonical, "alternates": [], "x_default": None}
        alternates = [
            (version.locale.language_code, version.get_full_url(request))
            for version in versions
        ]
        alternates = [(code, url) for code, url in alternates if url]
        several = len(alternates) > 1
        return {
            "canonical": page.get_full_url(request),
            "alternates": alternates if several else [],
            "x_default": source.get_full_url(request) if source and several else None,
        }
