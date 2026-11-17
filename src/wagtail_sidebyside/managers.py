from django.db import models
from django.db.models import F
from django.utils import timezone


class TranslationStateManager(models.Manager):
    def for_page(self, page):
        return self.filter(page_id=page.pk).first()

    def store(
        self,
        page,
        entries: dict,
        removed: list | None = None,
        awaiting_source: bool = False,
    ):
        defaults = {"entries": entries, "awaiting_source": awaiting_source}
        if removed is not None:
            defaults["removed"] = removed
        self.update_or_create(page_id=page.pk, defaults=defaults)


class AIUsageManager(models.Manager):
    def this_month(self):
        return self.get_or_create(month=timezone.localdate().replace(day=1))[0]

    def add(self, input_tokens: int, output_tokens: int, cost):
        """Count one machine translation request in this month's usage."""
        usage = self.this_month()
        self.filter(pk=usage.pk).update(
            requests=F("requests") + 1,
            input_tokens=F("input_tokens") + input_tokens,
            output_tokens=F("output_tokens") + output_tokens,
            cost=F("cost") + cost,
        )
