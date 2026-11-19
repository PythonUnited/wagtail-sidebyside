from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.db.models import F
from django.utils import timezone
from wagtail.models import Page


def _key(obj) -> dict:
    """The generic key of a page (as a Page) or snippet."""
    model = Page if isinstance(obj, Page) else obj._meta.concrete_model
    return {
        "content_type": ContentType.objects.get_for_model(model),
        "object_id": str(obj.pk),
    }


class TranslationStateManager(models.Manager):
    def for_object(self, obj):
        return self.filter(**_key(obj)).first()

    def store(
        self,
        obj,
        entries: dict,
        removed: list | None = None,
        awaiting_source: bool = False,
    ):
        defaults = {"entries": entries, "awaiting_source": awaiting_source}
        if removed is not None:
            defaults["removed"] = removed
        self.update_or_create(**_key(obj), defaults=defaults)

    def forget(self, obj):
        self.filter(**_key(obj)).delete()


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
