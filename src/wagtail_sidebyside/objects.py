"""Pages and snippets are translated the same way. The few places where they
differ (URLs, permissions, the editor's panels, saving) are here.

A snippet takes part when its model has TranslatableMixin and is registered
as a snippet. RevisionMixin, DraftStateMixin and LockableMixin are optional:
saving goes through Wagtail's own create and edit actions, which handle them.
"""

from django.contrib.admin.utils import quote
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.urls import reverse
from wagtail.actions.registry import action_registry
from wagtail.admin.panels import TabbedInterface
from wagtail.hooks import search_for_hooks
from wagtail.models import (
    DraftStateMixin,
    LockableMixin,
    Page,
    PreviewableMixin,
    RevisionMixin,
    TranslatableMixin,
)
from wagtail.permissions import policy_registry
from wagtail.snippets.models import get_snippet_models

# Fields of Wagtail's model mixins: state, not content.
MIXIN_FIELDS = frozenset(
    field.name
    for mixin in (TranslatableMixin, RevisionMixin, DraftStateMixin, LockableMixin)
    for field in mixin._meta.local_fields
)


def is_page(obj) -> bool:
    return isinstance(obj, Page)


def _snippet_models() -> list:
    # Snippets are often registered in wagtail_hooks.py, which Wagtail loads
    # on first use of a hook: not yet in e.g. a management command.
    search_for_hooks()
    return get_snippet_models()


def is_translatable_snippet(model) -> bool:
    return (
        issubclass(model, TranslatableMixin)
        and not issubclass(model, Page)
        and model in _snippet_models()
    )


def snippet_models() -> list:
    """The translated snippet models, in the order they were registered."""
    return [model for model in _snippet_models() if is_translatable_snippet(model)]


def get_snippet(app_label: str, model_name: str, pk: str):
    for model in snippet_models():
        if (model._meta.app_label, model._meta.model_name) == (app_label, model_name):
            return get_object_or_404(model, pk=pk)
    raise Http404


def specific(obj):
    return obj.specific if is_page(obj) else obj


def latest(obj):
    """The latest version: the latest revision of a page or snippet with
    drafts, otherwise the object itself."""
    if isinstance(obj, DraftStateMixin):
        return obj.get_latest_revision_as_object()
    return obj


def has_drafts(obj) -> bool:
    return isinstance(obj, DraftStateMixin)


def is_live(obj) -> bool:
    return not has_drafts(obj) or obj.live


def has_unpublished_changes(obj) -> bool:
    return has_drafts(obj) and obj.has_unpublished_changes


def never_published(obj) -> bool:
    return has_drafts(obj) and obj.first_published_at is None


def is_previewable(obj) -> bool:
    return isinstance(obj, PreviewableMixin) and obj.is_previewable()


def title(obj) -> str:
    return obj.get_admin_display_title() if is_page(obj) else str(obj)


def edit_url(obj) -> str:
    if is_page(obj):
        return reverse("wagtailadmin_pages:edit", args=[obj.pk])
    return reverse(obj.snippet_viewset.get_url_name("edit"), args=[quote(obj.pk)])


def listing_url(obj) -> str:
    """Where to go back to: the page explorer or the snippet listing."""
    if is_page(obj):
        return reverse("wagtailadmin_explore", args=[obj.get_parent().pk])
    return reverse(obj.snippet_viewset.get_url_name("list"))


def history_url(obj) -> str | None:
    if is_page(obj):
        return reverse("wagtailadmin_pages:history", args=[obj.pk])
    if isinstance(obj, RevisionMixin):
        return reverse(
            obj.snippet_viewset.get_url_name("history"), args=[quote(obj.pk)]
        )
    return None


def _url_args(source, locale) -> list:
    code = locale.language_code
    if is_page(source):
        return [source.pk, code]
    meta = source._meta
    return [meta.app_label, meta.model_name, quote(source.pk), code]


def translate_url(source, locale) -> str:
    name = "translate" if is_page(source) else "translate_snippet"
    return reverse(f"sidebyside:{name}", args=_url_args(source, locale))


def preview_url(source, locale) -> str:
    name = "preview" if is_page(source) else "preview_snippet"
    return reverse(f"sidebyside:{name}", args=_url_args(source, locale))


def can(user, obj, action: str) -> bool:
    """action: "change" or "publish"."""
    if is_page(obj):
        permissions = obj.permissions_for_user(user)
        return (
            permissions.can_edit() if action == "change" else permissions.can_publish()
        )
    if action == "publish" and not has_drafts(obj):
        return can(user, obj, "change")
    return policy_registry.get_by_type(type(obj)).user_has_permission_for_instance(
        user, action, obj
    )


def can_view_history(user, obj) -> bool:
    if is_page(obj):
        return obj.permissions_for_user(user).can_view_revisions()
    return history_url(obj) is not None and can(user, obj, "change")


def lock(obj):
    return obj.get_lock() if isinstance(obj, LockableMixin) else None


def editor_tabs(model) -> list:
    """The panels of the editor's tabs. An editor without tabs is one tab."""
    if issubclass(model, Page):
        handler = model.get_edit_handler()
    else:
        handler = model.snippet_viewset.get_edit_handler()
    return handler.children if isinstance(handler, TabbedInterface) else [handler]


def create(obj, user, publish: bool):
    """Save a new snippet the way Wagtail's create view does."""
    action = action_registry.get_action_class(type(obj), "create")(
        obj, user=user, publish=publish
    )
    return action.execute(skip_permission_checks=True)


def reload_state(obj):
    """The state of Wagtail's mixins (live, latest_revision, ...) from the
    database, e.g. after publishing it through another instance. The content
    in obj stays as it is."""
    names = [
        field.attname
        for field in obj._meta.concrete_fields
        if field.name in MIXIN_FIELDS - {"locale", "translation_key"}
    ]
    obj.refresh_from_db(fields=names)


def save(obj, user, publish: bool):
    """Save an edit the way Wagtail's edit view does: a revision if the model
    has them, published (publish) or as a draft for a model with drafts, else
    live right away. Validated, also as a draft. Returns the revision or None."""
    action = action_registry.get_action_class(type(obj), "edit")(
        obj, user=user, publish=publish and has_drafts(obj), clean=True
    )
    action.execute(skip_permission_checks=True)
    return action.revision
