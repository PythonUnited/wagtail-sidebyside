"""A small demo site, for trying the package and making the screenshots.

    uv run python -m tests.demo

Creates tests/demo.sqlite3 with a few French pages and a footer snippet,
with their English translations, then runs the server on http://localhost:8000/cms/ (admin/admin).
Machine translation uses a fake backend, no API key needed.
"""

import json
import os
import sys

import django
from django.core.management import call_command

BODY = [
    {"type": "heading", "value": "La recette", "id": "h1"},
    {
        "type": "rich_text",
        "value": "<p>Battez trois oeufs, ajoutez <b>beaucoup de fromage</b> "
        "et faites cuire a feu doux. Voir aussi "
        '<a href="https://fr.wikipedia.org/wiki/Omelette">l\'omelette</a>.</p>',
        "id": "r1",
    },
    {"type": "quote", "value": "Omelette du fromage", "id": "q1"},
    {"type": "chart", "value": {"date": None}, "id": "m1"},
]


def create_content():
    from django.contrib.auth import get_user_model
    from wagtail.models import Locale, Page, Site
    from wagtail.users.models import UserProfile

    from tests.testapp.models import Footer, TestPage
    from wagtail_sidebyside.use_cases.sync_tree import SyncTree
    from wagtail_sidebyside.use_cases.translate_page import TranslatePage

    if TestPage.objects.exists():
        return
    admin = get_user_model().objects.create_superuser(
        "admin", "admin@example.com", "admin"
    )
    profile = UserProfile.get_for_user(admin)
    profile.preferred_language = "en"
    profile.save()
    fr = Locale.objects.get_or_create(language_code="fr")[0]
    en = Locale.objects.get_or_create(language_code="en")[0]
    root = Page.get_first_root_node()
    home = root.add_child(
        instance=TestPage(
            title="Laboratoire",
            slug="laboratoire",
            locale=fr,
            hero_title="Bienvenue au laboratoire",
        )
    )
    home.save_revision().publish()
    Site.objects.update_or_create(
        is_default_site=True, defaults={"root_page": home, "hostname": "localhost"}
    )
    Page.objects.filter(depth=2).exclude(pk=home.pk).delete()
    recipes = home.add_child(
        instance=TestPage(title="Recettes", slug="recettes", locale=fr)
    )
    recipes.save_revision().publish()
    omelette = recipes.add_child(
        instance=TestPage(
            title="Omelette du fromage",
            slug="omelette-du-fromage",
            locale=fr,
            hero_title="Omelette du fromage",
            body=json.dumps(BODY),
        )
    )
    omelette.save_revision().publish()

    contact = home.add_child(
        instance=TestPage(title="Contact", slug="contact", locale=fr)
    )
    contact.save_revision().publish()

    # A translated snippet: its English version is created along with it.
    Footer.objects.create(
        heading="Contact",
        text="<p>Laboratoire du fromage, Paris</p>"
        '<p><a href="mailto:fromage@example.com">fromage@example.com</a></p>',
        locale=fr,
    )

    # Translate some of the English pages, leave the rest to try (contact is
    # not started: it shows the French text).
    for page in (home, recipes, omelette, contact):
        SyncTree.create_translations(page)
    for page, values in (
        (home, {"title": "Laboratory", "slug": "laboratory"}),
        (recipes, {"title": "Recipes", "slug": "recipes"}),
        (omelette, {"title": "Cheese omelette", "body.h1": "The recipe"}),
    ):
        source = page.specific
        target = source.get_translation(en).specific
        rows = TranslatePage.rows(source, target)
        TranslatePage.save(
            source, target, rows, values, set(values), set(), set(), None, True
        )


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tests.demo_settings")
    django.setup()
    call_command("migrate", verbosity=0)
    create_content()
    call_command("runserver", *(sys.argv[1:] or ["8000"]))


if __name__ == "__main__":
    main()
