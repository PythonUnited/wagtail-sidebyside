"""Not started translations: status, overview filter and <head> links."""

import pytest
from django.template import Context, Template
from django.test import RequestFactory
from wagtail.models import Site

from tests.test_translate import _save, pages  # noqa: F401
from wagtail_sidebyside.models import TranslationState
from wagtail_sidebyside.use_cases.page_status import (
    NOT_STARTED,
    HeadLinks,
    PageStatus,
)


@pytest.fixture
def site(pages):  # noqa: F811
    source, _target = pages
    Site.objects.update_or_create(
        is_default_site=True,
        defaults={
            "hostname": "localhost",
            "port": 80,
            "root_page": source.get_parent(),
        },
    )


def _publish(page):
    page.get_latest_revision().publish()
    page.refresh_from_db()


def _not_started(target):
    # As created by SyncTree.create_translations.
    TranslationState.objects.store(target, {})


def test_status_not_started(pages):  # noqa: F811
    source, target = pages
    _not_started(target)
    (status,) = PageStatus.for_page(source)
    assert status.state == NOT_STARTED and status.needs_work

    _save(source, target, {"title": "Home"})
    (status,) = PageStatus.for_page(source)
    assert status.started and status.state != NOT_STARTED


def test_translation_without_state_counts_as_started(pages):  # noqa: F811
    _source, target = pages
    # Translated before the app was installed.
    assert PageStatus.started(target)


def test_overview_filters(pages):  # noqa: F811
    source, target = pages
    _not_started(target)
    ids = lambda show: [page.pk for page, _s in PageStatus.overview(show)]  # noqa: E731
    assert source.pk in ids("all")
    assert source.pk in ids("work")
    assert source.pk not in ids("started")

    _save(source, target, {"title": "Home"})
    assert source.pk in ids("started")


def test_head_links_not_started(pages, site):  # noqa: F811
    source, target = pages
    _not_started(target)
    links = HeadLinks.for_page(target)
    assert links["canonical"] == source.get_full_url()
    assert links["alternates"] == []

    links = HeadLinks.for_page(source)
    assert links["canonical"] == source.get_full_url()
    assert links["alternates"] == []  # the only live, translated version


def test_head_links_started(pages, site):  # noqa: F811
    source, target = pages
    _save(source, target, {"title": "Home"})
    _publish(target)
    links = HeadLinks.for_page(target)
    assert links["canonical"] == target.get_full_url()
    assert links["canonical"] != source.get_full_url()
    assert dict(links["alternates"]) == {
        "fr": source.get_full_url(),
        "en": target.get_full_url(),
    }
    assert links["x_default"] == source.get_full_url()


def test_head_tag(pages, site):  # noqa: F811
    source, target = pages
    _save(source, target, {"title": "Home"})
    _publish(target)
    request = RequestFactory().get("/")
    html = Template("{% load sidebyside %}{% sidebyside_head %}").render(
        Context({"page": source, "request": request})
    )
    assert f'<link rel="canonical" href="{source.get_full_url()}">' in html
    assert 'hreflang="en"' in html and 'hreflang="x-default"' in html
    assert (
        Template("{% load sidebyside %}{% sidebyside_head %}")
        .render(Context({}))
        .strip()
        == ""
    )
