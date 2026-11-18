"""Translations follow their source page: they cannot be moved or deleted on
their own."""

import pytest
from django.urls import reverse
from wagtail.models import Page

from tests.test_translate import _english, pages  # noqa: F401


@pytest.fixture
def admin(client, django_user_model):
    user = django_user_model.objects.create_superuser("guard", "guard@example.com", "x")
    client.force_login(_english(user))
    return client


def _exists(page):
    return Page.objects.filter(pk=page.pk).exists()


def test_delete_translation_refused(admin, pages):  # noqa: F811
    _source, target = pages
    url = reverse("wagtailadmin_pages:delete", args=[target.pk])
    response = admin.post(url, follow=True)
    assert _exists(target)
    assert "is a translation" in response.content.decode()


def test_delete_source_takes_translation_along(admin, pages):  # noqa: F811
    source, target = pages
    url = reverse("wagtailadmin_pages:delete", args=[source.pk])
    assert admin.get(url).status_code == 200
    admin.post(url)
    assert not _exists(source) and not _exists(target)


def test_move_translation_refused(admin, pages):  # noqa: F811
    source, target = pages
    destination = target.get_parent().get_parent()  # the root
    url = reverse("wagtailadmin_pages:move_confirm", args=[target.pk, destination.pk])
    admin.post(url)
    assert Page.objects.get(pk=target.pk).get_parent().pk == target.get_parent().pk


def test_bulk_delete_translation_refused(admin, pages):  # noqa: F811
    source, target = pages
    url = reverse("wagtail_bulk_action", args=["wagtailcore", "page", "delete"])
    admin.post(f"{url}?id={target.pk}")
    assert _exists(target)
    # Together with its source it may go.
    admin.post(f"{url}?id={source.pk}&id={target.pk}")
    assert not _exists(source)


def test_page_without_source_can_be_deleted(admin, pages):  # noqa: F811
    _source, target = pages
    # An English page that is not a translation of a French one.
    orphan = target.get_parent().add_child(
        instance=type(target)(
            title="Only English", slug="only-en", locale=target.locale
        )
    )
    admin.post(reverse("wagtailadmin_pages:delete", args=[orphan.pk]))
    assert not _exists(orphan)
