"""Machine translation with Claude, directly (Anthropic API) or through
Microsoft Foundry (Azure). Needs the "claude" extra:
pip install "wagtail-sidebyside[claude]".

Settings in SIDEBYSIDE: "AI_PROVIDER" = "anthropic" | "foundry" (empty = no
machine translation), "AI_MODEL" and "AI_PRICES". Credentials come from the
environment, read by the SDK: ANTHROPIC_API_KEY, or ANTHROPIC_FOUNDRY_API_KEY
plus ANTHROPIC_FOUNDRY_RESOURCE.
"""

import importlib.util
import json
import os
from decimal import Decimal

from django.utils.translation import gettext as _

from ..conf import config
from . import TranslationError, Translator, Usage

DEFAULT_MODEL = "claude-opus-5-5"

# USD per million input / output tokens, for the usage estimate. Override or
# extend with SIDEBYSIDE["AI_PRICES"] when prices change.
DEFAULT_PRICES = {
    "claude-opus-5-5": (4, 20),
    "claude-sonnet-5-5": (2, 10),
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-fable-5-2": (8, 40),
}

PROVIDERS = {
    "anthropic": "Claude (Anthropic API)",
    "foundry": "Claude via Microsoft Foundry (Azure)",
}

SYSTEM_PROMPT = """You translate the content of a web page from {source} to {target}.
Each input item is one field of the page. Translate every item.
- Items with format "html" contain HTML. Keep every tag and attribute exactly as
  it is, including Wagtail tags such as <a linktype="page" id="3"> and
  <embed ... />, and translate only the text.
- Keep names, numbers, dates, units and URLs as they are, unless {target}
  writes them differently.
- Stay close to the tone and length of the source. Add no explanations.
Return one translation per item, with the id of that item."""

SCHEMA = {
    "type": "object",
    "properties": {
        "translations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"id": {"type": "integer"}, "text": {"type": "string"}},
                "required": ["id", "text"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["translations"],
    "additionalProperties": False,
}


class ClaudeTranslator(Translator):
    status_template = "sidebyside/translators/claude_status.html"

    @property
    def provider(self) -> str:
        return config().get("AI_PROVIDER") or ""

    @property
    def model(self) -> str:
        return config().get("AI_MODEL") or DEFAULT_MODEL

    @staticmethod
    def installed() -> bool:
        return importlib.util.find_spec("anthropic") is not None

    def missing_credentials(self) -> list[str]:
        """Environment variables the configured provider needs but lacks."""
        env = os.environ.get
        if self.provider == "anthropic":
            if env("ANTHROPIC_API_KEY") or env("ANTHROPIC_AUTH_TOKEN"):
                return []
            return ["ANTHROPIC_API_KEY"]
        if self.provider == "foundry":
            missing = (
                []
                if env("ANTHROPIC_FOUNDRY_API_KEY")
                else ["ANTHROPIC_FOUNDRY_API_KEY"]
            )
            if not (
                env("ANTHROPIC_FOUNDRY_RESOURCE") or env("ANTHROPIC_FOUNDRY_BASE_URL")
            ):
                missing.append("ANTHROPIC_FOUNDRY_RESOURCE")
            return missing
        return []

    def available(self) -> bool:
        return (
            self.provider in PROVIDERS
            and self.installed()
            and not self.missing_credentials()
        )

    def status(self) -> dict:
        return {
            "provider": self.provider,
            "provider_name": PROVIDERS.get(self.provider, ""),
            "model": self.model,
            "installed": self.installed(),
            "missing": self.missing_credentials(),
            "available": self.available(),
        }

    def price(self) -> tuple[Decimal, Decimal] | None:
        """USD per million input and output tokens of the model, if known."""
        prices = {**DEFAULT_PRICES, **config().get("AI_PRICES", {})}
        found = prices.get(self.model)
        return tuple(Decimal(str(value)) for value in found) if found else None

    def cost(self, usage: Usage) -> Decimal | None:
        rates = self.price()
        if rates is None:
            return None
        million = Decimal(1_000_000)
        return (
            usage.input_tokens * rates[0] / million
            + usage.output_tokens * rates[1] / million
        )

    def client(self):
        import anthropic

        if self.provider == "foundry":
            return anthropic.AnthropicFoundry()
        return anthropic.Anthropic()

    def check(self) -> Usage:
        """Call the model once with a tiny request (a few tokens)."""
        import anthropic

        if not self.available():
            raise TranslationError(_("Machine translation is not configured."))
        try:
            message = self.client().messages.create(
                model=self.model,
                max_tokens=16,
                messages=[{"role": "user", "content": "Reply with: OK"}],
                output_config={"effort": "low"},
            )
        except anthropic.APIError as error:
            raise TranslationError(_error_message(error)) from error
        return _usage(message)

    def translate(self, items, source, target, glossary="", instructions=""):
        import anthropic

        system = SYSTEM_PROMPT.format(source=source, target=target)
        if glossary.strip():
            system += (
                f"\n\nGlossary, always use these translations:\n{glossary.strip()}"
            )
        if instructions.strip():
            system += f"\n\nAdditional instructions:\n{instructions.strip()}"
        payload = [
            {"id": index, "format": "html" if is_html else "text", "text": text}
            for index, (text, is_html) in enumerate(items)
        ]
        request = {
            "model": self.model,
            "max_tokens": 64000,
            "system": system,
            "messages": [
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}
            ],
            "output_config": {
                "effort": "medium",
                "format": {"type": "json_schema", "schema": SCHEMA},
            },
        }

        client = self.client()
        try:
            if self.provider == "anthropic":
                # On a policy decline the API retries on a fallback model itself.
                # Not available on Foundry, where it would need a second deployment.
                stream = client.beta.messages.stream(
                    **request,
                    betas=["server-side-fallback-2026-07-01"],
                    fallbacks="default",
                )
            else:
                stream = client.messages.stream(**request)
            with stream as response:
                message = response.get_final_message()
        except anthropic.APIError as error:
            raise TranslationError(_error_message(error)) from error

        if message.stop_reason == "refusal":
            raise TranslationError(_("Machine translation declined this content."))
        if message.stop_reason == "max_tokens":
            raise TranslationError(_("Too much text at once. Translate fewer fields."))
        text = next(block.text for block in message.content if block.type == "text")
        by_id = {item["id"]: item["text"] for item in json.loads(text)["translations"]}
        return [by_id.get(index, "") for index in range(len(items))], _usage(message)


def _usage(message) -> Usage:
    return Usage(message.usage.input_tokens, message.usage.output_tokens)


def _error_message(error) -> str:
    import anthropic

    if isinstance(error, anthropic.AuthenticationError):
        return _("Machine translation: invalid API key.")
    if isinstance(error, anthropic.PermissionDeniedError):
        return _("Machine translation: this key has no access to the model.")
    if isinstance(error, anthropic.NotFoundError):
        return _("Machine translation: model not found.")
    if isinstance(error, anthropic.RateLimitError):
        return _("Machine translation is busy, try again in a minute.")
    if isinstance(error, anthropic.BadRequestError) and "credit" in str(error).lower():
        return _("Machine translation: no credit left on the account.")
    if isinstance(error, anthropic.APIConnectionError):
        return _("Machine translation: no connection.")
    if isinstance(error, anthropic.APIStatusError):
        return _("Machine translation failed (%(status)s).") % {
            "status": error.status_code
        }
    return _("Machine translation failed.")
