import json
import re

import pytest
from django.urls import reverse
from wagtail.models import Locale, Page
from wagtail.rich_text import RichText

from tests.testapp.models import TestPage
from wagtail_sidebyside.fields import SYNCED, TEXT_KINDS, page_texts, page_units
from wagtail_sidebyside.models import TranslationState
from wagtail_sidebyside.use_cases.translate_page import (
    DONE,
    OUTDATED,
    REVIEW,
    TODO,
    TranslatePage,
)

BODY = [
    {"type": "heading", "value": "Omelette du fromage", "id": "h1"},
    {"type": "rich_text", "value": "<p>Le fromage <b>fond</b></p>", "id": "r1"},
    {"type": "chart", "value": {"date": None}, "id": "m1"},
    {
        "type": "columns",
        "id": "c1",
        "value": {
            "columns": [
                {
                    "type": "item",
                    "id": "col1",
                    "value": [
                        {"type": "paragraph", "value": "Gauche", "id": "p1"},
                    ],
                },
                {
                    "type": "item",
                    "id": "col2",
                    "value": [
                        {"type": "paragraph", "value": "Droite", "id": "p2"},
                    ],
                },
            ]
        },
    },
]


@pytest.fixture
def pages(db):
    fr = Locale.get_default()
    en, _ = Locale.objects.get_or_create(language_code="en")
    root = Page.get_first_root_node()
    fr_home = root.add_child(instance=TestPage(title="FR", slug="sbs-fr", locale=fr))
    fr_home.copy_for_translation(en)
    source = fr_home.add_child(
        instance=TestPage(
            title="Accueil",
            slug="accueil",
            locale=fr,
            hero_title="Bienvenue",
            theme="teal",
            body=json.dumps(BODY),
        )
    )
    target = source.copy_for_translation(en)
    return source, TestPage.objects.get(pk=target.pk)


def _latest(page):
    return TestPage.objects.get(pk=page.pk).get_latest_revision_as_object()


def _rows(source, target):
    return TranslatePage.rows(_latest(source), _latest(target))


def _save(source, target, values, changed=None, confirmed=(), machine=()):
    source = _latest(source)
    target = _latest(target)
    rows = TranslatePage.rows(source, target)
    TranslatePage.save(
        source,
        target,
        rows,
        values,
        set(values) if changed is None else changed,
        set(confirmed),
        set(machine),
        None,
        publish=False,
    )


class TestPageUnits:
    def test_paths_and_kinds(self, pages):
        source, _ = pages
        units = {unit.path: unit for unit in page_units(source)}
        assert units["title"].source == "Accueil"
        assert units["slug"].kind == "text"
        assert units["hero_title"].source == "Bienvenue"
        assert units["body.h1"].kind == "text"
        assert units["body.r1"].kind == "richtext"
        assert units["body.m1"].kind == SYNCED
        assert units["body.c1.columns.col2.p2"].source == "Droite"
        # Choices and images are not translatable.
        assert "theme" not in units
        assert "header_image" not in units


class TestTranslatePage:
    def test_new_translation_is_all_todo(self, pages):
        rows = _rows(*pages)
        # Fields empty in the source (meta description) are optional, not work.
        texts = [row for row in rows if row.unit.kind in TEXT_KINDS and row.unit.source]
        assert {row.status for row in texts} == {TODO}

    def test_save_writes_translations_and_keeps_rest_from_source(self, pages):
        source, target = pages
        _save(source, target, {"title": "Home", "body.h1": "Cheese omelette"})

        target = _latest(target)
        texts = page_texts(target)
        assert texts["title"] == "Home"
        assert texts["body.h1"] == "Cheese omelette"
        # Untranslated units fall back to the source text.
        assert texts["body.c1.columns.col1.p1"] == "Gauche"
        assert target.theme == "teal"
        statuses = {row.unit.path: row.status for row in _rows(source, target)}
        assert statuses["body.h1"] == DONE
        assert statuses["body.r1"] == TODO

    def test_source_change_makes_translation_outdated(self, pages):
        source, target = pages
        _save(source, target, {"body.h1": "Cheese omelette"})

        source = _latest(source)
        source.body[0].value = "Omelette du bon fromage"
        source.save_revision()

        row = next(row for row in _rows(source, target) if row.unit.path == "body.h1")
        assert row.status == OUTDATED
        assert row.translation == "Cheese omelette"
        assert ("insert", "bon ") in row.diff

    def test_saving_unchanged_keeps_outdated_until_confirmed(self, pages):
        source, target = pages
        _save(source, target, {"body.h1": "Cheese omelette"})
        source = _latest(source)
        source.body[0].value = "Omelette du bon fromage"
        source.save_revision()

        _save(source, target, {"body.h1": "Cheese omelette"}, changed=set())
        statuses = {row.unit.path: row.status for row in _rows(source, target)}
        assert statuses["body.h1"] == OUTDATED

        _save(
            source,
            target,
            {"body.h1": "Cheese omelette"},
            changed=set(),
            confirmed={"body.h1"},
        )
        statuses = {row.unit.path: row.status for row in _rows(source, target)}
        assert statuses["body.h1"] == DONE

    def test_existing_translation_gets_baseline(self, pages):
        source, target = pages
        target = _latest(target)
        target.hero_title = "Welcome"
        target.save_revision()

        statuses = {row.unit.path: row.status for row in _rows(source, target)}
        assert statuses["hero_title"] == DONE
        assert statuses["title"] == TODO
        assert TranslationState.objects.for_object(target) is None

    def test_source_of(self, pages):
        source, target = pages
        assert TranslatePage.source_of(target).pk == source.pk
        assert TranslatePage.source_of(source) is None


class TestViews:
    @pytest.fixture
    def client(self, client, django_user_model):
        user = django_user_model.objects.create_superuser("sbs", "sbs@example.com", "x")
        client.force_login(user)
        return client

    def test_edit_translation_redirects(self, client, pages):
        source, target = pages
        response = client.get(reverse("wagtailadmin_pages:edit", args=[target.pk]))
        assert response.status_code == 302
        assert response.url == reverse("sidebyside:translate", args=[source.pk, "en"])

    def test_translate_get_and_post(self, client, pages):
        source, target = pages
        url = reverse("sidebyside:translate", args=[source.pk, "en"])
        assert client.get(url).status_code == 200

        response = client.post(url, {"title": "Home", "action-publish": "1"})
        assert response.status_code == 302
        target.refresh_from_db()
        assert target.live
        assert target.title == "Home"
        assert target.slug == "home"


class TestAlignment:
    def test_translation_with_own_block_ids_is_matched_by_position(self, pages):
        source, target = pages
        target = _latest(target)
        body = json.loads(json.dumps(BODY).replace('"id": "', '"id": "en-'))
        body[0]["value"] = "Cheese omelette"
        body[3]["value"]["columns"][1]["value"][0]["value"] = "Right"
        target.body = json.dumps(body)
        target.save_revision()

        rows = {row.unit.path: row for row in _rows(source, target)}
        assert rows["body.h1"].status == DONE
        assert rows["body.h1"].translation == "Cheese omelette"
        assert rows["body.c1.columns.col2.p2"].translation == "Right"
        assert rows["body.r1"].status == TODO

        # Saving the form as shown keeps the translations and adopts the
        # source ids.
        shown = {path: row.translation for path, row in rows.items() if row.translation}
        _save(source, target, shown, changed=set())
        texts = page_texts(_latest(target))
        assert texts["body.h1"] == "Cheese omelette"
        assert texts["body.c1.columns.col2.p2"] == "Right"

    def test_moved_block_does_not_shift_the_rest(self, pages):
        source, target = pages
        target = _latest(target)
        body = json.loads(json.dumps(BODY).replace('"id": "', '"id": "en-'))
        body[0]["value"] = "Cheese omelette"
        body[1]["value"] = "<p>The cheese melts</p>"
        # Source has heading, rich_text, map, ...; target has the map first.
        body.insert(0, body.pop(2))
        target.body = json.dumps(body)
        target.save_revision()

        rows = {row.unit.path: row for row in _rows(source, target)}
        assert rows["body.h1"].translation == "Cheese omelette"
        assert rows["body.r1"].translation == "<p>The cheese melts</p>"


class TestPageStatus:
    def test_status_counts(self, pages):
        from wagtail_sidebyside.use_cases.page_status import PageStatus

        source, target = pages
        _save(source, target, {"title": "Home", "body.h1": "Cheese omelette"})
        (status,) = PageStatus.for_object(source)
        assert status.locale.language_code == "en"
        assert status.state == TODO
        assert status.outdated == 0
        assert status.todo > 0

    def test_overview_lists_source_pages_only(self, pages):
        from wagtail_sidebyside.use_cases.page_status import PageStatus

        source, target = pages
        page_ids = [
            row.source.pk for section in PageStatus.overview() for row in section.rows
        ]
        assert source.pk in page_ids
        assert target.pk not in page_ids


class TestPhase2Views:
    @pytest.fixture
    def client(self, client, django_user_model):
        user = django_user_model.objects.create_superuser(
            "sbs2", "sbs2@example.com", "x"
        )
        client.force_login(user)
        return client

    def test_overview_dashboard_and_source_edit_render(self, client, pages):
        source, _target = pages
        response = client.get(reverse("sidebyside:overview"))
        assert response.status_code == 200
        assert source.title in response.content.decode()
        assert client.get(reverse("wagtailadmin_home")).status_code == 200
        response = client.get(reverse("wagtailadmin_pages:edit", args=[source.pk]))
        assert response.status_code == 200
        assert (
            reverse("sidebyside:translate", args=[source.pk, "en"])
            in response.content.decode()
        )


class FakeStream:
    def __init__(self, message):
        self.message = message

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def get_final_message(self):
        return self.message


class FakeClient:
    """Answers every request with "EN:" + the source text."""

    def __init__(self):
        self.requests = []
        self.beta = self
        self.messages = self

    def create(self, **request):
        from types import SimpleNamespace

        self.requests.append(request)
        return SimpleNamespace(usage=SimpleNamespace(input_tokens=10, output_tokens=5))

    def stream(self, **request):
        from types import SimpleNamespace

        self.requests.append(request)
        items = json.loads(request["messages"][0]["content"])
        text = json.dumps(
            {
                "translations": [
                    {"id": i["id"], "text": "EN:" + i["text"]} for i in items
                ]
            }
        )
        return FakeStream(
            SimpleNamespace(
                stop_reason="end_turn",
                content=[SimpleNamespace(type="text", text=text)],
                usage=SimpleNamespace(input_tokens=1_000_000, output_tokens=100_000),
            )
        )


@pytest.fixture
def fake_ai(settings, monkeypatch):
    from wagtail_sidebyside.translators.claude import ClaudeTranslator

    settings.SIDEBYSIDE = {**settings.SIDEBYSIDE, "AI_PROVIDER": "anthropic"}
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    client = FakeClient()
    monkeypatch.setattr(ClaudeTranslator, "client", lambda self: client)
    return client


class TestMachineTranslation:
    def test_ai_module_builds_request_and_parses_answer(self, fake_ai):
        from wagtail_sidebyside.translators import get_translator

        result, usage = get_translator().translate(
            [("Omelette du fromage", False), ("<p>Le <b>fromage</b></p>", True)],
            "French",
            "English",
            glossary="fromage = cheese",
        )
        assert result == ["EN:Omelette du fromage", "EN:<p>Le <b>fromage</b></p>"]
        assert usage.input_tokens == 1_000_000
        (request,) = fake_ai.requests
        assert request["fallbacks"] == "default"
        assert "fromage = cheese" in request["system"]
        assert json.loads(request["messages"][0]["content"])[1]["format"] == "html"

    def test_refusal_becomes_translation_error(self, fake_ai, monkeypatch):
        from types import SimpleNamespace

        from wagtail_sidebyside import translators as ai
        from wagtail_sidebyside.translators import get_translator

        refused = SimpleNamespace(stop_reason="refusal", content=[])
        monkeypatch.setattr(fake_ai, "stream", lambda **request: FakeStream(refused))
        with pytest.raises(ai.TranslationError):
            get_translator().translate([("x", False)], "French", "English")

    def test_not_available_without_provider(self, settings):
        from wagtail_sidebyside.use_cases.machine_translate import MachineTranslate

        settings.SIDEBYSIDE = {**settings.SIDEBYSIDE, "AI_PROVIDER": ""}
        assert not MachineTranslate.available()


class TestMachineTranslationView:
    @pytest.fixture
    def client(self, client, django_user_model):
        user = django_user_model.objects.create_superuser(
            "sbs3", "sbs3@example.com", "x"
        )
        client.force_login(user)
        return client

    def test_translate_all_then_save_marks_review_then_confirm(
        self, client, pages, fake_ai
    ):
        source, target = pages
        url = reverse("sidebyside:translate", args=[source.pk, "en"])

        response = client.post(url, {"ai": "all"})
        assert response.status_code == 200
        html = response.content.decode()
        assert 'name="machine:body.h1" value="EN:Omelette du fromage"' in html
        # Nothing is saved by translating.
        statuses = {row.unit.path: row.status for row in _rows(source, target)}
        assert statuses["body.h1"] == TODO

        # Save the AI text unchanged for the heading, edited for the title.
        response = client.post(
            url,
            {
                "title": "Home",
                "body.h1": "EN:Omelette du fromage",
                "machine:body.h1": "EN:Omelette du fromage",
                "machine:title": "EN:Accueil",
            },
        )
        assert response.status_code == 302
        statuses = {row.unit.path: row.status for row in _rows(source, target)}
        assert statuses["body.h1"] == REVIEW
        assert statuses["title"] == DONE

        response = client.post(
            url,
            {
                "title": "Home",
                "body.h1": "EN:Omelette du fromage",
                "confirm": "body.h1",
            },
        )
        statuses = {row.unit.path: row.status for row in _rows(source, target)}
        assert statuses["body.h1"] == DONE


class TestSyncTree:
    def test_create_translations_copies_and_publishes_with_live_source(self, pages):
        from wagtail_sidebyside.use_cases.sync_tree import SyncTree

        source, target = pages
        child = source.add_child(instance=TestPage(title="Enfant", slug="enfant"))
        (created,) = SyncTree.create_translations(child)
        assert created.locale.language_code == "en"
        assert created.get_parent().pk == target.pk
        created.refresh_from_db()
        assert created.live
        assert SyncTree.create_translations(child) == []

    def test_publishing_source_updates_translation(self, pages):
        source, target = pages
        _save(source, target, {"body.h1": "Cheese omelette"})

        source = _latest(source)
        source.theme = "night"
        source.body[2].value["date"] = None
        source.hero_title = "Bienvenue chez Dexter"
        source.save_revision().publish()

        target = TestPage.objects.get(pk=target.pk)
        assert target.live
        assert target.theme == "night"
        texts = page_texts(target)
        assert texts["body.h1"] == "Cheese omelette"
        # Untranslated text follows the source.
        assert texts["hero_title"] == "Bienvenue chez Dexter"

    def test_pending_translation_draft_is_not_published(self, pages):
        source, target = pages
        _save(source, target, {"body.h1": "Cheese omelette"})
        TestPage.objects.get(pk=target.pk).get_latest_revision().publish()
        _save(source, target, {"body.h1": "The big cheese omelette"})  # pending draft

        source = _latest(source)
        source.theme = "night"
        source.save_revision().publish()

        live = TestPage.objects.get(pk=target.pk)
        assert page_texts(live)["body.h1"] == "Cheese omelette"
        assert live.theme == "teal"
        draft = _latest(target)
        assert page_texts(draft)["body.h1"] == "The big cheese omelette"
        assert draft.theme == "night"

    def test_cascade_returns_translations_of_source_pages_only(self, pages):
        from wagtail_sidebyside.use_cases.sync_tree import SyncTree

        source, target = pages
        result = SyncTree.cascade([source, target])
        assert list(result) == [source]
        assert [page.pk for page in result[source]] == [target.pk]


class TestTreeHooks:
    @pytest.fixture
    def client(self, client, django_user_model):
        user = django_user_model.objects.create_superuser(
            "sbs4", "sbs4@example.com", "x"
        )
        client.force_login(user)
        return client

    def test_adding_in_translation_tree_continues_in_source_tree(self, client, pages):
        source, target = pages
        url = reverse("wagtailadmin_pages:add", args=["testapp", "testpage", target.pk])
        response = client.get(url)
        assert response.status_code == 302
        assert response.url == reverse(
            "wagtailadmin_pages:add", args=["testapp", "testpage", source.pk]
        )

    def test_explorer_has_translation_bar_to_switch_language(self, client, pages):
        source, target = pages
        html = client.get(
            reverse("wagtailadmin_explore", args=[target.pk])
        ).content.decode()
        assert 'class="sbs-bar"' in html
        assert f'href="{reverse("wagtailadmin_explore", args=[source.pk])}"' in html

    def test_creating_source_page_creates_translation(self, client, pages):
        source, target = pages
        url = reverse("wagtailadmin_pages:add", args=["testapp", "testpage", source.pk])
        response = client.post(
            url,
            {
                "title": "Nouveau",
                "slug": "nouveau",
                "theme": "blue",
                "body-count": "0",
                "action-publish": "1",
            },
        )
        assert response.status_code == 302, response.content.decode()[:2000]
        source.refresh_from_db()
        new = source.get_children().get(slug="nouveau")
        translation = new.get_translation(Locale.objects.get(language_code="en"))
        assert translation.get_parent().pk == target.pk
        assert translation.live


class TestOrphans:
    def test_text_without_source_counterpart_blocks_auto_publish(self, pages):
        source, target = pages
        target = _latest(target)
        body = json.loads(json.dumps(BODY))
        body.append({"type": "heading", "value": "Only in English", "id": "extra"})
        target.body = json.dumps(body)
        target.save_revision().publish()

        source = _latest(source)
        orphans = TranslatePage.orphans(source, _latest(target))
        assert [unit.source for unit in orphans] == ["Only in English"]

        source.theme = "night"
        source.save_revision().publish()
        live = TestPage.objects.get(pk=target.pk)
        assert live.theme == "teal"
        assert "Only in English" in page_texts(live).values()


class TestAlignmentText:
    def test_text_blocks_win_over_a_moved_image(self, pages):
        from tests.testapp.models import Body
        from wagtail_sidebyside.fields import _align

        def block(kind, id, value):
            return {"type": kind, "id": id, "value": value}

        image = {"image": None, "caption": ""}
        source = [
            block("image", "i1", image),
            block("heading", "h1", "Titre"),
            block("paragraph", "p1", "Texte"),
            block("heading", "h2", "Titre 2"),
            block("paragraph", "p2", "Texte 2"),
            block("image", "i2", image),
        ]
        target = [
            block("heading", "x1", "Title"),
            block("paragraph", "x2", "Text"),
            block("image", "x3", image),
            block("heading", "x4", "Title 2"),
            block("paragraph", "x5", "Text 2"),
            block("image", "x6", image),
        ]
        ids = [item["id"] for item in _align(Body(), source, target)]
        assert ids[:2] == ["h1", "p1"]
        assert ids[3:5] == ["h2", "p2"]


class TestEditorHeader:
    @pytest.fixture
    def user(self, django_user_model):
        return django_user_model.objects.create_superuser(
            "sbs5", "sbs5@example.com", "x"
        )

    def test_visible_buttons_for_few_languages(self, client, user, pages):
        source, _target = pages
        client.force_login(user)
        html = client.get(
            reverse("wagtailadmin_pages:edit", args=[source.pk])
        ).content.decode()
        url = reverse("sidebyside:translate", args=[source.pk, "en"])
        assert re.search(
            rf'<a href="{url}"\s+class="button button-small sbs-bar__button', html
        )
        assert "sbs-bar-menu" not in html

    def test_dropdown_for_more_languages(self, client, user, pages):
        source, _target = pages
        Locale.objects.get_or_create(language_code="nl")
        Locale.objects.get_or_create(language_code="de")
        client.force_login(user)
        html = client.get(
            reverse("wagtailadmin_pages:edit", args=[source.pk])
        ).content.decode()
        assert "sbs-bar-menu" in html
        assert html.count('class="sbs-bar-menu__item"') == 3

    def test_admin_in_users_language(self, client, user, pages):
        from wagtail.users.models import UserProfile

        profile = UserProfile.get_for_user(user)
        profile.preferred_language = "nl"
        profile.save()
        client.force_login(user)
        html = client.get(reverse("sidebyside:overview")).content.decode()
        assert "Nog te doen" in html


class TestTranslateScreenLayout:
    def test_uses_wagtail_header_bar_and_footer(self, client, django_user_model, pages):
        source, _target = pages
        user = django_user_model.objects.create_superuser(
            "sbs6", "sbs6@example.com", "x"
        )
        client.force_login(user)
        html = client.get(
            reverse("sidebyside:translate", args=[source.pk, "en"])
        ).content.decode()
        assert "w-slim-header" in html
        assert 'class="sbs-bar"' in html
        assert 'aria-current="page"' in html
        assert 'class="footer w-grid' in html
        assert 'name="action-publish"' in html


class TestBaselineHeuristic:
    def test_old_source_copy_and_stub_are_not_translations(self, pages):
        source, target = pages
        # An earlier revision of the source, later changed.
        old_source = _latest(source)
        old_source.body[1].value = RichText("<p>Le fromage fond encore</p>")
        old_source.save_revision()
        source = _latest(source)
        source.body[1].value = RichText("<p>Le fromage <b>fond</b></p>")
        source.save_revision()

        target = _latest(target)
        body = json.loads(json.dumps(BODY))
        body[0]["value"] = "Cheese omelette"  # translated
        body[1]["value"] = "<p>Le fromage fond encore</p>"  # copy of an older source
        body[3]["value"]["columns"][0]["value"][0]["value"] = "Left"  # translated
        target.body = json.dumps(body)
        target.title = "Accueil"  # source text
        target.save_revision()

        statuses = {row.unit.path: row.status for row in _rows(source, target)}
        assert statuses["body.h1"] == DONE
        assert statuses["body.r1"] == TODO
        assert statuses["body.c1.columns.col1.p1"] == DONE
        assert statuses["title"] == TODO

    def test_stub(self):
        from wagtail_sidebyside.fields import Unit

        unit = Unit("x", "x", "richtext", "<p>Un texte assez long pour la regle</p>")
        assert not TranslatePage._looks_translated(unit, "<p>/</p>", set())
        assert TranslatePage._looks_translated(unit, "<p>A text long enough</p>", set())


class TestSameInBothLanguages:
    def test_same_stays_ticked_and_follows_source(
        self, client, django_user_model, pages
    ):
        source, target = pages
        user = django_user_model.objects.create_superuser(
            "sbs7", "sbs7@example.com", "x"
        )
        client.force_login(user)
        url = reverse("sidebyside:translate", args=[source.pk, "en"])
        client.post(url, {"title": "Home", "same": "body.h1"})

        rows = {row.unit.path: row for row in _rows(source, target)}
        assert rows["body.h1"].same
        assert rows["body.h1"].status == DONE
        assert page_texts(_latest(target))["body.h1"] == "Omelette du fromage"
        html = client.get(url).content.decode()
        assert 'value="body.h1" checked' in html

        # The source changes: the translation follows, nothing gets outdated.
        source = _latest(source)
        source.body[0].value = "Omelette du bon fromage"
        source.save_revision().publish()
        rows = {row.unit.path: row for row in _rows(source, target)}
        assert rows["body.h1"].same
        assert rows["body.h1"].status == DONE
        assert page_texts(_latest(target))["body.h1"] == "Omelette du bon fromage"

        # Untick: back to a normal, untranslated field.
        client.post(url, {"title": "Home", "body.h1": ""})
        rows = {row.unit.path: row for row in _rows(source, target)}
        assert not rows["body.h1"].same
        assert rows["body.h1"].status == TODO


class TestNewTranslation:
    def test_copy_of_earlier_source_version_is_not_a_translation(self, pages):
        from wagtail_sidebyside.use_cases.sync_tree import SyncTree

        source, target = pages
        # Autosave: the page is created while the title is still being typed.
        child = source.add_child(instance=TestPage(title="Omele", slug="omele"))
        (translation,) = SyncTree.create_translations(child)
        child.title = "Omelette du fromage"
        child.slug = "omelette-du-fromage"
        child.save_revision(overwrite_revision=child.latest_revision)

        rows = {row.unit.path: row for row in _rows(child, translation)}
        assert rows["title"].status == TODO
        assert rows["slug"].status == TODO

        TestPage.objects.get(pk=child.pk).get_latest_revision().publish()
        translation = TestPage.objects.get(pk=translation.pk)
        assert translation.title == "Omelette du fromage"
        assert translation.slug == "omelette-du-fromage"

    def test_ai_skips_fields_marked_same(
        self, client, django_user_model, pages, fake_ai
    ):
        source, _target = pages
        user = django_user_model.objects.create_superuser(
            "sbs8", "sbs8@example.com", "x"
        )
        client.force_login(user)
        url = reverse("sidebyside:translate", args=[source.pk, "en"])
        html = client.post(url, {"ai": "all", "same": "body.h1"}).content.decode()
        assert 'name="machine:body.h1"' not in html
        assert 'name="machine:title"' in html
        assert 'value="body.h1" checked' in html


class TestValidation:
    @pytest.fixture
    def client(self, client, django_user_model):
        user = django_user_model.objects.create_superuser(
            "sbs9", "sbs9@example.com", "x"
        )
        client.force_login(user)
        return client

    def test_empty_form_saves_with_source_texts(self, client, pages):
        source, target = pages
        url = reverse("sidebyside:translate", args=[source.pk, "en"])
        assert client.post(url, {}).status_code == 302
        assert _latest(target).title == "Accueil"

    def test_too_long_title_and_bad_slug_show_errors(self, client, pages):
        source, target = pages
        url = reverse("sidebyside:translate", args=[source.pk, "en"])
        response = client.post(url, {"title": "x" * 300, "slug": "no spaces allowed"})
        assert response.status_code == 200
        errors = response.context["form"].errors
        assert "title" in errors
        assert "slug" in errors
        assert _latest(target).title == "Accueil"


class TestSameKeepsTypedText:
    def test_typed_text_is_kept_aside_and_returns_when_unticked(
        self, client, django_user_model, pages
    ):
        source, target = pages
        user = django_user_model.objects.create_superuser(
            "sbs10", "sbs10@example.com", "x"
        )
        client.force_login(user)
        url = reverse("sidebyside:translate", args=[source.pk, "en"])

        client.post(url, {"body.h1": "blabla", "same": "body.h1"})
        row = {row.unit.path: row for row in _rows(source, target)}["body.h1"]
        assert row.same and row.translation == "blabla"
        assert page_texts(_latest(target))["body.h1"] == "Omelette du fromage"

        client.post(url, {"body.h1": "blabla"})
        row = {row.unit.path: row for row in _rows(source, target)}["body.h1"]
        assert not row.same and row.status == DONE
        assert page_texts(_latest(target))["body.h1"] == "blabla"


class TestCopySource:
    @pytest.fixture
    def client(self, client, django_user_model):
        user = django_user_model.objects.create_superuser(
            "sbs11", "sbs11@example.com", "x"
        )
        client.force_login(user)
        return client

    def test_copy_fills_field_without_saving(self, client, pages):
        source, target = pages
        url = reverse("sidebyside:translate", args=[source.pk, "en"])
        response = client.post(url, {"copy": "body.h1"})
        assert response.status_code == 200
        assert response.context["form"]["body.h1"].value() == "Omelette du fromage"
        assert 'name="machine:body.h1"' not in response.content.decode()
        statuses = {row.unit.path: row.status for row in _rows(source, target)}
        assert statuses["body.h1"] == TODO

    def test_unchanged_copy_stays_todo_edited_copy_is_done(self, client, pages):
        source, target = pages
        url = reverse("sidebyside:translate", args=[source.pk, "en"])
        from wagtail.admin.rich_text import get_rich_text_editor_widget

        # Draftail posts its own JSON format, not HTML.
        rich = get_rich_text_editor_widget().format_value(
            "<p>The cheese <b>melts</b></p>"
        )
        client.post(
            url,
            {
                "body.h1": "Omelette du fromage",
                "copied:body.h1": "Omelette du fromage",
                "body.r1": rich,
            },
        )
        statuses = {row.unit.path: row.status for row in _rows(source, target)}
        assert statuses["body.h1"] == TODO
        assert statuses["body.r1"] == DONE

    def test_text_equal_to_source_is_kept_unless_an_unchanged_copy(self, client, pages):
        source, target = pages
        url = reverse("sidebyside:translate", args=[source.pk, "en"])
        # AI (or the editor) gives the same text as the source: a translation.
        client.post(url, {"title": "Accueil", "machine:title": "Accueil"})
        row = {row.unit.path: row for row in _rows(source, target)}["title"]
        assert row.status == REVIEW and row.translation == "Accueil"
        client.post(url, {"title": "Accueil", "body.h1": "Omelette du fromage"})
        row = {row.unit.path: row for row in _rows(source, target)}["body.h1"]
        assert row.status == DONE and row.translation == "Omelette du fromage"


class TestLivePreview:
    def test_preview_shows_unsaved_translation(self, client, django_user_model, pages):
        source, target = pages
        user = django_user_model.objects.create_superuser(
            "sbs12", "sbs12@example.com", "x"
        )
        client.force_login(user)
        url = reverse("sidebyside:preview", args=[source.pk, "en"])

        response = client.post(
            url, {"body.h1": "The great cheese omelette", "hero_title": "Welcome"}
        )
        assert response.json() == {"is_valid": True, "is_available": True}
        html = client.get(url).content.decode()
        assert "The great cheese omelette" in html
        # Nothing saved.
        assert page_texts(_latest(target))["body.h1"] == "Omelette du fromage"

    def test_translate_screen_has_side_panels(self, client, django_user_model, pages):
        source, _target = pages
        user = django_user_model.objects.create_superuser(
            "sbs13", "sbs13@example.com", "x"
        )
        client.force_login(user)
        html = client.get(
            reverse("sidebyside:translate", args=[source.pk, "en"])
        ).content.decode()
        assert 'data-side-panel="preview"' in html or "data-side-panel-toggle" in html
        assert "data-minimap-container" in html
        assert "data-panel-anchor" in html
        assert "data-edit-form" in html


class TestImageOverride:
    @pytest.fixture
    def images(self, db):
        from wagtail.images import get_image_model
        from wagtail.images.tests.utils import get_test_image_file

        Image = get_image_model()
        return [
            Image.objects.create(title=title, file=get_test_image_file())
            for title in ("fr", "en", "fr2")
        ]

    @pytest.fixture
    def page_with_image(self, pages, images):
        source, target = pages
        for page in (_latest(source), _latest(target)):
            body = json.loads(json.dumps(BODY))
            body.append(
                {
                    "type": "image",
                    "id": "i1",
                    "value": {"image": images[0].pk, "caption": "Une image"},
                }
            )
            page.body = json.dumps(body)
            page.save_revision()
        return source, target

    @pytest.fixture
    def client(self, client, django_user_model):
        user = django_user_model.objects.create_superuser(
            "sbs14", "sbs14@example.com", "x"
        )
        client.force_login(user)
        return client

    def _image(self, page):
        return page_texts(_latest(page))["body.i1.image"]

    def test_image_follows_source_unless_overridden(
        self, client, page_with_image, images
    ):
        source, target = page_with_image
        url = reverse("sidebyside:translate", args=[source.pk, "en"])
        units = {unit.path: unit for unit in page_units(_latest(source))}
        assert units["body.i1.image"].kind == "image"
        # header_image is in TestPage.translation_exclude.
        assert "header_image" not in units

        # A chosen image without the tick is ignored.
        client.post(url, {"body.i1.image": images[1].pk})
        assert self._image(target) == str(images[0].pk)

        client.post(url, {"override": "body.i1.image", "body.i1.image": images[1].pk})
        assert self._image(target) == str(images[1].pk)
        row = {row.unit.path: row for row in _rows(source, target)}["body.i1.image"]
        assert row.override

        # The source gets another image: the translation keeps its own.
        fr = _latest(source)
        fr.body[4].value["image"] = images[2]
        fr.save_revision().publish()
        assert self._image(target) == str(images[1].pk)

        # Untick: follows the source again.
        client.post(url, {"body.i1.image": images[1].pk})
        assert self._image(target) == str(images[2].pk)


class TestConnectionStatus:
    def test_not_available_without_credentials(self, settings, monkeypatch):
        from wagtail_sidebyside.translators import get_translator

        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
        settings.SIDEBYSIDE = {**settings.SIDEBYSIDE, "AI_PROVIDER": "anthropic"}
        assert get_translator().status()["missing"] == ["ANTHROPIC_API_KEY"]
        assert not get_translator().available()
        settings.SIDEBYSIDE = {**settings.SIDEBYSIDE, "AI_PROVIDER": "foundry"}
        assert get_translator().missing_credentials() == [
            "ANTHROPIC_FOUNDRY_API_KEY",
            "ANTHROPIC_FOUNDRY_RESOURCE",
        ]

    def test_check_success_and_no_credit(self, fake_ai, monkeypatch):
        import anthropic
        import httpx2

        from wagtail_sidebyside import translators as ai
        from wagtail_sidebyside.translators import get_translator

        get_translator().check()
        assert fake_ai.requests[-1]["max_tokens"] == 16

        def no_credit(**request):
            response = httpx2.Response(
                400, request=httpx2.Request("POST", "https://api")
            )
            raise anthropic.BadRequestError(
                "Your credit balance is too low", response=response, body=None
            )

        monkeypatch.setattr(fake_ai, "create", no_credit)
        from django.utils import translation

        with (
            translation.override("en"),
            pytest.raises(ai.TranslationError, match="credit"),
        ):
            get_translator().check()

    def test_settings_page_shows_status_and_check_button(
        self, client, django_user_model, fake_ai
    ):
        user = django_user_model.objects.create_superuser(
            "sbs15", "sbs15@example.com", "x"
        )
        client.force_login(_english(user))
        html = client.get(
            reverse("wagtailsettings:edit", args=["sidebyside", "translationsettings"]),
            follow=True,
        ).content.decode()
        assert "claude-opus-5-5" in html
        assert reverse("sidebyside:ai_check") in html

        response = client.post(reverse("sidebyside:ai_check"), follow=True)
        assert "Connection works" in response.content.decode()


class TestRemovedTranslations:
    @pytest.fixture
    def client(self, client, django_user_model):
        user = django_user_model.objects.create_superuser(
            "sbs16", "sbs16@example.com", "x"
        )
        client.force_login(_english(user))
        return client

    def test_removed_block_keeps_translation_and_reuses_it(self, client, pages):
        source, target = pages
        url = reverse("sidebyside:translate", args=[source.pk, "en"])
        client.post(url, {"body.h1": "Cheese omelette"})

        # The heading is removed from the source and the source published.
        fr = _latest(source)
        del fr.body[0]
        fr.save_revision().publish()
        removed = TranslatePage.removed(TestPage.objects.get(pk=target.pk))
        assert removed == [
            {
                "label": "Body > Heading",
                "kind": "text",
                "source": "Omelette du fromage",
                "text": "Cheese omelette",
            }
        ]
        assert "Removed from the source" in client.get(url).content.decode()

        # A heading with the same text comes back (new block id): reused.
        fr = _latest(source)
        fr.body.insert(0, ("heading", "Omelette du fromage"))
        fr.save_revision()
        new_path = next(
            unit.path
            for unit in page_units(_latest(source))
            if unit.source == "Omelette du fromage"
        )
        row = {row.unit.path: row for row in _rows(source, target)}[new_path]
        assert (
            row.reused and row.status == REVIEW and row.translation == "Cheese omelette"
        )

        # Saved as shown: stays "to review", and leaves the removed list.
        client.post(url, {new_path: "Cheese omelette"})
        row = {row.unit.path: row for row in _rows(source, target)}[new_path]
        assert row.status == REVIEW and not row.reused
        assert TranslatePage.removed(TestPage.objects.get(pk=target.pk)) == []

    def test_discard(self, client, pages):
        from wagtail_sidebyside.models import TranslationState

        source, target = pages
        TranslationState.objects.store(
            target, {}, [{"label": "x", "kind": "text", "source": "a", "text": "b"}]
        )
        url = reverse("sidebyside:translate", args=[source.pk, "en"])
        client.post(url, {"discard": "0"})
        assert TranslatePage.removed(target) == []


def _english(user):
    """The admin follows the user's language; LANGUAGE_CODE is French."""
    from wagtail.users.models import UserProfile

    profile = UserProfile.get_for_user(user)
    profile.preferred_language = "en"
    profile.save()
    return user


class TestUsageAndBudget:
    @pytest.fixture
    def client(self, client, django_user_model):
        user = django_user_model.objects.create_superuser(
            "sbs17", "sbs17@example.com", "x"
        )
        client.force_login(_english(user))
        return client

    def test_usage_is_counted_and_budget_stops_ai(self, client, pages, fake_ai):
        from decimal import Decimal

        from wagtail_sidebyside.models import AIUsage, TranslationSettings
        from wagtail_sidebyside.use_cases.machine_translate import MachineTranslate

        source, _target = pages
        url = reverse("sidebyside:translate", args=[source.pk, "en"])
        client.post(url, {"ai": "body.h1"})

        usage = AIUsage.objects.this_month()
        assert usage.requests == 1
        # Opus 5.5: 1M input tokens * $4 + 100k output tokens * $20 / 1M.
        assert usage.cost == Decimal("6.0000")

        config = TranslationSettings.load()
        config.monthly_budget = Decimal("5.00")
        config.save()
        assert MachineTranslate.budget_reached()
        assert not MachineTranslate.available()
        html = client.get(url).content.decode()
        assert 'name="ai"' not in html
        assert "budget for this month is used up" in html

        settings_html = client.get(
            reverse("wagtailsettings:edit", args=["sidebyside", "translationsettings"]),
            follow=True,
        ).content.decode()
        assert "$6.00 / $5.00" in settings_html
        assert "monthly budget is reached" in settings_html


class TestFieldOrder:
    def test_units_follow_the_page_editor(self, pages):
        source, _target = pages
        paths = [unit.path for unit in page_units(_latest(source))]
        # Content tab (title, hero title, body), then promote tab (slug).
        assert paths.index("title") < paths.index("hero_title") < paths.index("body.h1")
        assert paths.index("body.h1") < paths.index("slug")

    def test_metadata_section(self, pages):
        source, _target = pages
        units = {unit.path: unit for unit in page_units(_latest(source))}
        assert units["title"].section == "content"
        assert units["body.h1"].section == "content"
        assert units["slug"].section == "metadata"


class TestEmptyMetadata:
    def test_empty_metadata_is_shown_optional_and_can_be_filled(
        self, client, django_user_model, pages
    ):
        source, target = pages
        rows = {row.unit.path: row for row in _rows(source, target)}
        assert rows["seo_title"].unit.source == ""
        assert rows["search_description"].status == DONE
        assert rows["seo_title"].unit.section == "metadata"

        user = django_user_model.objects.create_superuser(
            "sbs18", "sbs18@example.com", "x"
        )
        client.force_login(user)
        url = reverse("sidebyside:translate", args=[source.pk, "en"])
        client.post(url, {"seo_title": "Cheese omelette recipe"})
        assert _latest(target).seo_title == "Cheese omelette recipe"
        row = {row.unit.path: row for row in _rows(source, target)}["seo_title"]
        assert row.status == DONE and row.translation == "Cheese omelette recipe"

        # The source gets a title tag: the translation is outdated.
        fr = _latest(source)
        fr.seo_title = "Recette de l'omelette"
        fr.save_revision()
        row = {row.unit.path: row for row in _rows(source, target)}["seo_title"]
        assert row.status == OUTDATED


class TestNeverAheadOfSource:
    @pytest.fixture
    def client(self, client, django_user_model):
        user = django_user_model.objects.create_superuser(
            "sbs19", "sbs19@example.com", "x"
        )
        client.force_login(_english(user))
        return client

    def _source_draft(self, source):
        fr = _latest(source)
        fr.theme = "night"
        fr.save_revision()

    def test_translation_only_is_published_against_live_source(self, client, pages):
        from wagtail_sidebyside.models import TranslationState

        source, target = pages
        self._source_draft(source)
        url = reverse("sidebyside:translate", args=[source.pk, "en"])
        html = client.get(url).content.decode()
        assert 'name="action-publish-together"' in html
        assert "Publish translation only" in html

        client.post(url, {"title": "Home", "action-publish": "1"})
        live = TestPage.objects.get(pk=target.pk)
        assert live.title == "Home"
        assert live.theme == "teal"  # the published source, not its draft
        assert _latest(target).theme == "night"
        assert TranslationState.objects.for_object(target).awaiting_source

        # Publishing the source publishes the waiting translation draft.
        TestPage.objects.get(pk=source.pk).get_latest_revision().publish()
        live = TestPage.objects.get(pk=target.pk)
        assert live.theme == "night" and live.title == "Home"
        assert not live.has_unpublished_changes

    def test_publish_source_and_translation_together(self, client, pages):
        source, target = pages
        self._source_draft(source)
        url = reverse("sidebyside:translate", args=[source.pk, "en"])
        client.post(url, {"title": "Home", "action-publish-together": "1"})
        assert TestPage.objects.get(pk=source.pk).theme == "night"
        live = TestPage.objects.get(pk=target.pk)
        assert live.theme == "night" and live.title == "Home"

    def test_unpublished_source_only_together(self, client, pages):
        from wagtail_sidebyside.use_cases.sync_tree import SyncTree

        source, _target = pages
        draft = source.add_child(
            instance=TestPage(title="Brouillon", slug="brouillon", live=False)
        )
        draft.save_revision()
        (translation,) = SyncTree.create_translations(draft)
        url = reverse("sidebyside:translate", args=[draft.pk, "en"])
        html = client.get(url).content.decode()
        assert 'name="action-publish-together"' in html
        assert 'name="action-publish"' not in html

        client.post(url, {"title": "Draft", "action-publish": "1"})
        assert not TestPage.objects.get(pk=translation.pk).live
