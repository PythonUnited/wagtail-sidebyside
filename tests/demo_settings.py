"""The demo site: python -m tests.demo"""

from tests.settings import *  # noqa: F403

SIDEBYSIDE = {
    "SOURCE_LOCALE": "fr",
    "TRANSLATOR": "tests.demo_translator.DemoTranslator",
}
