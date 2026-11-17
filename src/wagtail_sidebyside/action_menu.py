"""Footer actions of the translation screen, on top of Wagtail's own."""

from django.utils.translation import gettext_lazy as _
from wagtail.admin.action_menu import (
    ActionMenuItem,
    CancelWorkflowMenuItem,
    PublishMenuItem,
    RestartWorkflowMenuItem,
    SubmitForModerationMenuItem,
    WorkflowMenuItem,
)


class PublishTogetherMenuItem(ActionMenuItem):
    """Publish the source's draft and the translation at once."""

    name = "action-publish-together"
    label = _("Publish source and translation")
    icon_name = "upload"


class PublishTranslationOnlyMenuItem(PublishMenuItem):
    label = _("Publish translation only")


def adapt(action_menu, source_page, user):
    """Workflow actions are left out: the translation screen does not handle
    moderation, so they would only save a draft. When the source has
    unpublished changes, "Publish" publishes the translation only (against
    the published source), with "Publish source and translation" just above
    it. A source that was never published can only be published together
    with its translation."""
    items = action_menu.menu_items
    items[:] = [
        item
        for item in items
        if not isinstance(
            item,
            (
                SubmitForModerationMenuItem,
                WorkflowMenuItem,
                RestartWorkflowMenuItem,
                CancelWorkflowMenuItem,
            ),
        )
    ]
    if not source_page.has_unpublished_changes:
        return
    for index, item in enumerate(items):
        if isinstance(item, PublishMenuItem):
            if source_page.live:
                items[index] = PublishTranslationOnlyMenuItem(order=item.order)
            else:
                del items[index]
            if source_page.permissions_for_user(user).can_publish():
                items.insert(index, PublishTogetherMenuItem())
            return
