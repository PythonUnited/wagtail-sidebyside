from django.conf import settings
from wagtail.models import Locale


def config() -> dict:
    """The SIDEBYSIDE setting (a dict), see the README."""
    return getattr(settings, "SIDEBYSIDE", {})


def source_locale() -> Locale:
    """The main language of the site. Pages are created in this locale only,
    every other locale is a translation of it."""
    code = config().get("SOURCE_LOCALE")
    if code:
        return Locale.objects.get_for_language(code)
    return Locale.get_default()
