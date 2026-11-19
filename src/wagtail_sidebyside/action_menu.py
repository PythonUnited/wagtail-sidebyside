"""Footer actions of the translation screen, on top of Wagtail's own (the page
or the snippet action menu: other classes, the same item names)."""

import copy

from django.utils.translation import gettext_lazy as _
from wagtail.admin import action_menu as page_menu
from wagtail.snippets import action_menu as snippet_menu

from . import objects

# Workflow actions: the translation screen does not handle moderation.
WORKFLOW_ITEMS = (
    page_menu.SubmitForModerationMenuItem,
    page_menu.WorkflowMenuItem,
    page_menu.RestartWorkflowMenuItem,
    page_menu.CancelWorkflowMenuItem,
    snippet_menu.SubmitForModerationMenuItem,
    snippet_menu.WorkflowMenuItem,
    snippet_menu.RestartWorkflowMenuItem,
    snippet_menu.CancelWorkflowMenuItem,
)
PUBLISH_ITEMS = (page_menu.PublishMenuItem, snippet_menu.PublishMenuItem)


class _PublishTogether:
    """Publish the source's draft and the translation at once."""

    name = "action-publish-together"
    label = _("Publish source and translation")
    icon_name = "upload"


class PublishTogetherMenuItem(_PublishTogether, page_menu.ActionMenuItem):
    pass


class SnippetPublishTogetherMenuItem(_PublishTogether, snippet_menu.ActionMenuItem):
    pass


def adapt(action_menu, source, user):
    """Workflow actions are left out: they would only save a draft. When the
    source has unpublished changes, "Publish" publishes the translation only
    (against the published source), with "Publish source and translation"
    just above it. A source that was never published can only be published
    together with its translation."""
    items = action_menu.menu_items
    items[:] = [item for item in items if not isinstance(item, WORKFLOW_ITEMS)]
    if not objects.has_unpublished_changes(source):
        return
    for index, item in enumerate(items):
        if isinstance(item, PUBLISH_ITEMS):
            if source.live:
                # A copy: Wagtail shares its menu item instances between
                # requests.
                items[index] = copy.copy(item)
                items[index].label = _("Publish translation only")
            else:
                del items[index]
            if objects.can(user, source, "publish"):
                together = (
                    PublishTogetherMenuItem
                    if objects.is_page(source)
                    else SnippetPublishTogetherMenuItem
                )
                items.insert(index, together())
            return
