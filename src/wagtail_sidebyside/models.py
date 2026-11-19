from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils.translation import gettext_lazy as _
from wagtail.admin.panels import FieldPanel
from wagtail.contrib.settings.models import BaseGenericSetting, register_setting

from .managers import AIUsageManager, TranslationStateManager
from .panels import MachineTranslationStatusPanel


class TranslationState(models.Model):
    """Per translation (page or snippet): the source text each unit was
    translated from.

    The translated text itself lives in the object (its own revisions). This
    only tells us whether a unit is translated and whether its source changed
    since. entries = {path: {"source": "<source text at translation time>"}}
    The object is a generic key (pages: content type Page): removed with it,
    see signals.
    """

    content_type = models.ForeignKey(
        ContentType, on_delete=models.CASCADE, related_name="+"
    )
    object_id = models.CharField(max_length=255)
    entries = models.JSONField(default=dict)
    # Translated texts whose block was removed from the source, kept so they
    # are not silently lost: [{"label", "kind", "source", "text"}].
    removed = models.JSONField(default=list, blank=True)
    # The draft only waits for the source's draft to be published (the
    # translation itself was published): publishing the source publishes it.
    awaiting_source = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    objects = TranslationStateManager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["content_type", "object_id"],
                name="sidebyside_translationstate_object",
            )
        ]

    def __str__(self):
        return f"Translation state of {self.content_type} {self.object_id}"


@register_setting(icon="globe")
class TranslationSettings(BaseGenericSetting):
    ai_enabled = models.BooleanField(
        _("machine translation"),
        default=True,
        help_text=_("Show the buttons to translate with AI."),
    )
    glossary = models.TextField(
        _("glossary"),
        blank=True,
        help_text=_(
            "Terms that must always be translated the same way, one per line, "
            "e.g. 'fromage = cheese'. With more languages: "
            "'fromage = en: cheese | nl: kaas'."
        ),
    )
    instructions = models.TextField(
        _("instructions"),
        blank=True,
        help_text=_(
            "Extra instructions for the AI that apply to the whole site, one per "
            "line. Fixed translations of terms go in the glossary. Examples: "
            "'Use a formal, factual tone.' or 'Use a friendly, informal tone "
            "with short sentences.' 'Address the reader as you; in French always "
            "use vous.' 'Use British English spelling.' 'Keep product and place "
            "names as they are.' 'Write dates as 17 October 2026.'"
        ),
    )

    monthly_budget = models.DecimalField(
        _("monthly budget (USD)"),
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True,
        help_text=_(
            "Estimated cost of machine translation per month. When it is "
            "reached, the AI buttons are hidden until next month. Empty = no "
            "limit. The real bill is in the provider's console."
        ),
    )

    panels = [
        MachineTranslationStatusPanel(heading=_("Connection")),
        FieldPanel("ai_enabled"),
        FieldPanel("monthly_budget"),
        FieldPanel("glossary"),
        FieldPanel("instructions"),
    ]

    class Meta:
        verbose_name = _("translations")


class AIUsage(models.Model):
    """Machine translation usage per month, from the token counts each
    response reports. The cost is an estimate from SIDEBYSIDE["AI_PRICES"]."""

    month = models.DateField(unique=True)  # first day of the month
    requests = models.PositiveIntegerField(default=0)
    input_tokens = models.PositiveBigIntegerField(default=0)
    output_tokens = models.PositiveBigIntegerField(default=0)
    cost = models.DecimalField(max_digits=10, decimal_places=4, default=0)

    objects = AIUsageManager()

    def __str__(self):
        return f"Machine translation usage {self.month:%Y-%m}"
