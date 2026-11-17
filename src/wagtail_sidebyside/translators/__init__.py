"""Machine translation backends.

The backend is set with SIDEBYSIDE["TRANSLATOR"], a dotted path to a subclass
of Translator. The default is Claude (wagtail_sidebyside.translators.claude).
A backend for another service implements translate() and, where it can,
available(), status(), check() and cost().
"""

from dataclasses import dataclass
from decimal import Decimal

from django.utils.module_loading import import_string

from ..conf import config

DEFAULT_TRANSLATOR = "wagtail_sidebyside.translators.claude.ClaudeTranslator"


class TranslationError(Exception):
    """A translation request failed; the message is shown to the editor."""


@dataclass
class Usage:
    """What one request used, for the monthly usage and budget."""

    input_tokens: int = 0
    output_tokens: int = 0


class Translator:
    #: Template rendered in Settings > Translations (connection status and
    #: set-up help). Its context has "translator", "status" and "usage".
    status_template = "sidebyside/translators/status.html"

    def available(self) -> bool:
        """Whether the backend is configured, so the AI buttons are shown."""
        return True

    def status(self) -> dict:
        """Configuration shown in the settings, without calling the service."""
        return {"available": self.available()}

    def translate(
        self,
        items: list[tuple[str, bool]],
        source: str,
        target: str,
        glossary: str = "",
        instructions: str = "",
    ) -> tuple[list[str], Usage | None]:
        """Translate items (text, is_html) from language source to target
        (language names, e.g. "French"). Returns the translations in the same
        order, and the usage of the request. Raises TranslationError."""
        raise NotImplementedError

    def check(self) -> Usage | None:
        """A tiny request to test the connection. Raises TranslationError."""
        self.translate([("Test", False)], "English", "French")
        return None

    def cost(self, usage: Usage) -> Decimal | None:
        """Estimated cost in USD of a request, or None if unknown."""
        return None


def get_translator() -> Translator:
    return import_string(config().get("TRANSLATOR") or DEFAULT_TRANSLATOR)()
