"""Signals, not admin hooks, so scheduled publishing and saving or deleting
from code are covered too."""

from django.apps import apps
from django.db.models.signals import post_delete, post_save
from wagtail.models import Page, TranslatableMixin
from wagtail.signals import page_published, published

from . import objects
from .models import TranslationState
from .use_cases.sync_tree import SyncTree


def propagate_source_publish(sender, instance, revision, **kwargs):
    if SyncTree.is_source(instance):
        SyncTree.propagate(revision.as_object(), user=revision.user)


def forget_page(sender, instance, **kwargs):
    TranslationState.objects.forget(instance)


def snippet_saved(sender, instance, created, raw=False, update_fields=None, **kwargs):
    """A new source snippet gets its translations. Without drafts, a saved
    source is what is live, so the translations follow it right away (with
    drafts: on publish, see propagate_source_publish). A save of only
    Wagtail's own state (e.g. latest_revision) is not an edit."""
    if raw or not objects.is_translatable_snippet(sender):
        return
    if not SyncTree.is_source(instance):
        return
    if created:
        SyncTree.create_translations(instance)
    elif not objects.has_drafts(instance) and not (
        update_fields and set(update_fields) <= objects.MIXIN_FIELDS
    ):
        SyncTree.propagate(instance)


def snippet_published(sender, instance, revision, **kwargs):
    if objects.is_translatable_snippet(sender):
        propagate_source_publish(sender, instance, revision)


def snippet_deleted(sender, instance, **kwargs):
    """A deleted source snippet takes its translations along."""
    TranslationState.objects.forget(instance)
    if objects.is_translatable_snippet(sender) and SyncTree.is_source(instance):
        SyncTree.delete_translations(instance)


def connect():
    page_published.connect(
        propagate_source_publish, dispatch_uid="sidebyside_propagate"
    )
    post_delete.connect(forget_page, sender=Page, dispatch_uid="sidebyside_forget")
    # Per model: a receiver for all models would cost every delete elsewhere
    # its fast path. Whether a model is a snippet is only known later (they
    # are registered after the apps are ready), so that is checked on use.
    for model in apps.get_models():
        if issubclass(model, TranslatableMixin) and not issubclass(model, Page):
            uid = f"sidebyside_{model._meta.label_lower}"
            post_save.connect(snippet_saved, sender=model, dispatch_uid=uid)
            published.connect(snippet_published, sender=model, dispatch_uid=uid)
            post_delete.connect(snippet_deleted, sender=model, dispatch_uid=uid)
