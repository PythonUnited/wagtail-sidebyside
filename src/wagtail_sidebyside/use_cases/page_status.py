from dataclasses import dataclass

from django.urls import reverse
from django.utils.translation import gettext as _
from wagtail.models import Locale, Page

from ..conf import source_locale
from ..fields import TEXT_KINDS
from .translate_page import DONE, OUTDATED, REVIEW, TODO, TranslatePage

MISSING = "missing"


@dataclass
class Status:
    source: Page
    locale: Locale
    target: Page | None = None
    todo: int = 0
    outdated: int = 0
    review: int = 0

    @property
    def state(self) -> str:
        if self.target is None:
            return MISSING
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
    def overview(needs_work_only: bool = False) -> list[tuple[Page, list[Status]]]:
        """All source pages in tree order with their translation statuses."""
        pages = (
            Page.objects.filter(locale=source_locale(), depth__gt=1)
            .order_by("path")
            .specific()
        )
        result = [(page, PageStatus.for_page(page)) for page in pages]
        if needs_work_only:
            result = [
                (page, statuses)
                for page, statuses in result
                if any(status.needs_work for status in statuses)
            ]
        return result
