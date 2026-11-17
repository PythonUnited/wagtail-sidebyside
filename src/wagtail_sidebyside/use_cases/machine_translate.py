from django.utils.translation import get_language_info
from django.utils.translation import gettext as _

from ..fields import HTML, RICHTEXT, TEXT_KINDS
from ..models import AIUsage, TranslationSettings
from ..translators import TranslationError, Usage, get_translator

# Share of the monthly budget from which the settings show a warning.
BUDGET_WARNING = 0.8


class MachineTranslate:
    @staticmethod
    def configured() -> bool:
        """The translator backend is set up (key, package, ...)."""
        return get_translator().available()

    @staticmethod
    def available() -> bool:
        """The AI buttons are shown: configured, switched on, budget left."""
        return (
            MachineTranslate.configured()
            and TranslationSettings.load().ai_enabled
            and not MachineTranslate.budget_reached()
        )

    @staticmethod
    def translate(rows, paths, source_code: str, target_code: str) -> dict[str, str]:
        """Machine translations (path -> text) for the units of rows in paths."""
        units = [
            row.unit
            for row in rows
            if row.unit.path in paths and row.unit.kind in TEXT_KINDS
        ]
        if not units:
            return {}
        if MachineTranslate.budget_reached():
            raise TranslationError(
                _("The machine translation budget for this month is used up.")
            )
        config = TranslationSettings.load()
        texts, usage = get_translator().translate(
            [(unit.source, unit.kind in (RICHTEXT, HTML)) for unit in units],
            get_language_info(source_code)["name"],
            get_language_info(target_code)["name"],
            config.glossary,
            config.instructions,
        )
        MachineTranslate.record(usage)
        return {
            unit.path: text for unit, text in zip(units, texts, strict=True) if text
        }

    @staticmethod
    def check():
        """Settings, "Test connection": one tiny request, counted as usage."""
        MachineTranslate.record(get_translator().check())

    @staticmethod
    def record(usage: Usage | None):
        if usage is None:
            return
        cost = get_translator().cost(usage) or 0
        AIUsage.objects.add(usage.input_tokens, usage.output_tokens, cost)

    @staticmethod
    def budget_reached() -> bool:
        budget = TranslationSettings.load().monthly_budget
        return budget is not None and AIUsage.objects.this_month().cost >= budget

    @staticmethod
    def usage() -> dict:
        """This month's usage, for the settings screen."""
        usage = AIUsage.objects.this_month()
        budget = TranslationSettings.load().monthly_budget
        share = usage.cost / budget if budget else None
        return {
            "cost": usage.cost,
            "requests": usage.requests,
            "tokens": usage.input_tokens + usage.output_tokens,
            "budget": budget,
            "percent": min(int(share * 100), 100) if share is not None else None,
            "warning": share is not None and BUDGET_WARNING <= share < 1,
            "reached": share is not None and share >= 1,
            "price_known": get_translator().cost(Usage()) is not None,
        }
