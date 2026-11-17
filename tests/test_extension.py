"""The extension points: hooks and a custom translator backend."""

import pytest
from django.http import HttpResponse
from django.urls import reverse
from wagtail import blocks, hooks

from tests.test_translate import _english, _latest, _rows, pages  # noqa: F401
from wagtail_sidebyside.fields import SYNCED, page_units
from wagtail_sidebyside.translators import Translator, Usage


class EchoTranslator(Translator):
    """A custom backend: upper case "translations", one token per item."""

    def translate(self, items, source, target, glossary="", instructions=""):
        return [text.upper() for text, _is_html in items], Usage(len(items), len(items))


@pytest.fixture
def admin(client, django_user_model):
    user = django_user_model.objects.create_superuser("ext", "ext@example.com", "x")
    client.force_login(_english(user))
    return client


def test_block_kind_hook(pages):  # noqa: F811
    source, _target = pages

    def no_headings(block):
        if isinstance(block, blocks.CharBlock) and block.name == "heading":
            return False
        return None

    with hooks.register_temporarily("sidebyside_block_kind", no_headings):
        units = {unit.path: unit for unit in page_units(_latest(source))}
    # No text left in the heading block: shown as "copied from source".
    assert units["body.h1"].kind == SYNCED
    assert units["body.r1"].kind == "richtext"


def test_construct_rows_hook(pages):  # noqa: F811
    source, target = pages

    def without_title(rows, source, target):
        rows[:] = [row for row in rows if row.unit.path != "title"]

    with hooks.register_temporarily("sidebyside_construct_rows", without_title):
        paths = [row.unit.path for row in _rows(source, target)]
    assert "title" not in paths


def test_save_hooks(admin, pages):  # noqa: F811
    source, target = pages
    url = reverse("sidebyside:translate", args=[source.pk, "en"])
    calls = []

    def after(request, source_page, target_page, revision):
        calls.append(revision.pk)

    def stop(request, source_page, target_page):
        return HttpResponse("stopped")

    with hooks.register_temporarily("sidebyside_after_save_translation", after):
        admin.post(url, {"title": "Home"})
    assert len(calls) == 1

    with hooks.register_temporarily("sidebyside_before_save_translation", stop):
        response = admin.post(url, {"title": "Other"})
    assert response.content == b"stopped"
    assert _latest(target).title == "Home"


def test_custom_translator(admin, pages, settings):  # noqa: F811
    from wagtail_sidebyside.models import AIUsage

    settings.SIDEBYSIDE = {
        **settings.SIDEBYSIDE,
        "TRANSLATOR": "tests.test_extension.EchoTranslator",
    }
    source, _target = pages
    url = reverse("sidebyside:translate", args=[source.pk, "en"])
    html = admin.post(url, {"ai": "body.h1"}).content.decode()
    assert 'name="machine:body.h1" value="OMELETTE DU FROMAGE"' in html
    assert AIUsage.objects.this_month().input_tokens == 1
