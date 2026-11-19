"""Translated snippets: the same side-by-side screen and sync as pages."""

import re

import pytest
from django.urls import reverse
from wagtail.models import Locale

from tests.test_translate import _english, pages  # noqa: F401
from tests.testapp.models import Footer, Notice
from wagtail_sidebyside import objects
from wagtail_sidebyside.fields import RICHTEXT, TEXT, page_units
from wagtail_sidebyside.models import TranslationState
from wagtail_sidebyside.use_cases.page_status import NOT_STARTED, PageStatus
from wagtail_sidebyside.use_cases.translate_page import DONE, TODO, TranslatePage


@pytest.fixture
def locales(db):
    Locale.objects.get_or_create(language_code="en")
    return Locale.get_default(), Locale.objects.get(language_code="en")


@pytest.fixture
def admin(client, django_user_model):
    user = django_user_model.objects.create_superuser(
        "snippets", "snippets@example.com", "x"
    )
    client.force_login(_english(user))
    return client


@pytest.fixture
def footer(locales):
    fr, _en = locales
    return Footer.objects.create(
        heading="Contact", text="<p>Bamako, Mali</p>", colour="dark", locale=fr
    )


def _translation(obj, code="en"):
    return objects.specific(obj.get_translation(Locale.objects.get(language_code=code)))


def _url(source, code="en"):
    return objects.translate_url(source, Locale.objects.get(language_code=code))


class TestSync:
    def test_new_source_gets_its_translations(self, footer):
        target = _translation(footer)
        assert target.heading == "Contact"
        assert TranslationState.objects.for_object(target).entries == {}
        (status,) = PageStatus.for_object(footer)
        assert status.state == NOT_STARTED

    def test_units_leave_out_choices_and_wagtail_state(self, locales):
        fr, _en = locales
        notice = Notice.objects.create(text="Avis", locale=fr)
        assert [(unit.path, unit.kind) for unit in page_units(notice)] == [
            ("text", TEXT)
        ]
        footer = Footer.objects.create(heading="Pied", text="<p>x</p>", locale=fr)
        assert [(unit.path, unit.kind) for unit in page_units(footer)] == [
            ("heading", TEXT),
            ("text", RICHTEXT),
        ]

    def test_saved_source_without_drafts_is_followed(self, footer):
        target = _translation(footer)
        rows = TranslatePage.rows(footer, target)
        TranslatePage.save(
            footer,
            target,
            rows,
            {"heading": "Contact us"},
            {"heading"},
            set(),
            set(),
            None,
            publish=False,
        )
        footer.colour = "light"
        footer.text = "<p>Bamako</p>"
        footer.save()

        target = _translation(footer)
        assert target.heading == "Contact us"  # translated: stays
        assert target.text == "<p>Bamako</p>"  # untranslated: follows
        assert target.colour == "light"  # not translatable: follows
        rows = {row.unit.path: row for row in TranslatePage.rows(footer, target)}
        assert rows["heading"].status == DONE
        assert rows["text"].status == TODO

    def test_deleted_source_takes_translations_and_states_along(self, footer):
        target = _translation(footer)
        footer.delete()
        assert not Footer.objects.filter(pk=target.pk).exists()
        assert not TranslationState.objects.filter(object_id=str(target.pk)).exists()

    def test_deleted_page_takes_its_state_along(self, pages):  # noqa: F811
        _source, target = pages
        TranslationState.objects.store(target, {})
        target.delete()
        assert not TranslationState.objects.exists()


class TestDrafts:
    def test_translation_follows_publishing(self, locales):
        fr, _en = locales
        notice = objects.create(Notice(text="Avis", locale=fr), None, publish=False)
        target = _translation(notice)
        assert not target.live

        notice.text = "Avis important"
        notice.save_revision().publish()
        target = _translation(notice)
        assert target.live and target.text == "Avis important"

    def test_publish_translation(self, admin, locales):
        fr, _en = locales
        notice = objects.create(Notice(text="Avis", locale=fr), None, publish=True)
        response = admin.post(
            _url(notice), {"text": "Notice", "action-publish": "1"}, follow=True
        )
        assert response.status_code == 200
        target = _translation(notice)
        assert target.live and target.text == "Notice"
        assert not target.has_unpublished_changes


class TestAdmin:
    def test_translate_screen_saves_live(self, admin, footer):
        url = _url(footer)
        html = admin.get(url).content.decode()
        assert "Contact" in html and "action-save" in html
        admin.post(url, {"heading": "Contact us"})
        assert _translation(footer).heading == "Contact us"

    def test_rich_text_source_is_a_readonly_editor(self, admin, footer):
        html = admin.get(_url(footer)).content.decode()
        (source,) = re.findall(r'<input[^>]*name="sbs-readonly-[^>]*>', html)
        assert " disabled" in source  # not part of the form
        assert "&quot;readOnly&quot;: true" in source
        assert "Bamako, Mali" in source

    def test_editing_a_translation_opens_the_translate_screen(self, admin, footer):
        target = _translation(footer)
        response = admin.get(objects.edit_url(target))
        assert response.status_code == 302 and response.url == _url(footer)

    def test_source_editor_shows_the_translation_bar(self, admin, footer):
        html = admin.get(objects.edit_url(footer)).content.decode()
        assert "sbs-bar" in html and _url(footer) in html

    def test_create_in_source_locale_only(self, admin, locales):
        url = reverse(Footer.snippet_viewset.get_url_name("add"))
        response = admin.get(f"{url}?locale=en")
        assert response.status_code == 302 and response.url == f"{url}?locale=fr"

    def test_delete_translation_refused(self, admin, footer):
        target = _translation(footer)
        url = reverse(Footer.snippet_viewset.get_url_name("delete"), args=[target.pk])
        response = admin.post(url, follow=True)
        assert Footer.objects.filter(pk=target.pk).exists()
        assert "is a translation" in response.content.decode()

    def test_overview_lists_snippets(self, admin, footer):
        sections = PageStatus.overview()
        rows = {section.heading: section.rows for section in sections}
        assert [row.source for row in rows["Footers"]] == [footer]
        html = admin.get(reverse("sidebyside:overview")).content.decode()
        assert _url(footer) in html


TABLE = {
    "columns": [
        {"type": "text", "heading": "Station"},
        {"type": "text", "heading": ""},
    ],
    "rows": [{"values": ["Mopti", "crue"]}, {"values": ["Akka", "decrue"]}],
    "caption": "Niveaux",
}


class TestTable:
    def test_units_and_translations(self, locales):
        fr, _en = locales
        notice = objects.create(
            Notice(text="Avis", locale=fr, body=[("table", TABLE)]),
            None,
            publish=True,
        )
        block_id = notice.body[0].id
        units = {unit.path: unit.source for unit in page_units(notice)}
        prefix = f"body.{block_id}"
        assert units == {
            "text": "Avis",
            f"{prefix}.columns.0": "Station",
            f"{prefix}.rows.0.0": "Mopti",
            f"{prefix}.rows.0.1": "crue",
            f"{prefix}.rows.1.0": "Akka",
            f"{prefix}.rows.1.1": "decrue",
            f"{prefix}.caption": "Niveaux",
        }

        target = _translation(notice)
        rows = TranslatePage.rows(objects.latest(notice), objects.latest(target))
        values = {f"{prefix}.rows.0.1": "flood", f"{prefix}.caption": "Levels"}
        TranslatePage.save(
            objects.latest(notice),
            objects.latest(target),
            rows,
            values,
            set(values),
            set(),
            set(),
            None,
            publish=True,
        )
        table = Notice.objects.get(pk=target.pk).body[0].value
        assert [column["heading"] for column in table.columns] == ["Station", ""]
        assert [[cell.value for cell in row] for row in table.rows] == [
            ["Mopti", "flood"],
            ["Akka", "decrue"],
        ]
        assert table.caption == "Levels"
