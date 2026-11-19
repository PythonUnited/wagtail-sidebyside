import uuid

from django import template
from django.urls import reverse
from wagtail.admin.rich_text import get_rich_text_editor_widget
from wagtail.documents import get_document_model
from wagtail.images import get_image_model

from .. import objects
from ..fields import IMAGE
from ..use_cases.page_status import PageStatus
from ..use_cases.sync_tree import SyncTree
from ..use_cases.translate_page import TranslatePage

register = template.Library()


@register.inclusion_tag("sidebyside/includes/translation_bar.html")
def translation_bar(page, current_locale=None, mode="edit"):
    """Row with a button for the source and one per translation with its
    status, the same in the editor, the translation screen and the page
    explorer. page: the source page or snippet, or one of its translations.
    mode "edit": buttons open the editor / translation screen;
    mode "explore": buttons open the explorer of that language (pages)."""
    if page is None or not page.pk:
        return {"items": []}
    if not objects.is_page(page) and not objects.is_translatable_snippet(type(page)):
        return {"items": []}
    source = page if SyncTree.is_source(page) else TranslatePage.source_of(page)
    if source is None:
        return {"items": []}
    current = current_locale or page.locale

    def url(target, translate_url):
        if mode == "explore":
            return (
                reverse("wagtailadmin_explore", args=[target.pk])
                if target
                else translate_url
            )
        return translate_url

    items = [
        {
            "language": source.locale.get_display_name(),
            "state": "source",
            "label": None,
            "url": url(source, objects.edit_url(source)),
            "current": current.pk == source.locale_id,
        }
    ]
    for status in PageStatus.for_object(source):
        items.append(
            {
                "language": status.locale.get_display_name(),
                "state": status.state,
                "label": status.label,
                "url": url(status.target, status.url),
                "current": current.pk == status.locale.pk,
            }
        )
    return {"items": items}


@register.inclusion_tag("sidebyside/includes/object_preview.html")
def object_preview(unit):
    """Thumbnail of the image, or title of the document, a unit refers to."""
    model = get_image_model() if unit.kind == IMAGE else get_document_model()
    found = model.objects.filter(pk=unit.source).first() if unit.source else None
    return {"object": found, "is_image": unit.kind == IMAGE}


@register.simple_tag
def readonly_richtext(html, features=None):
    """Rich text in a read-only editor, so the source looks exactly like the
    translation's editor next to it (link types, anchors, images), not like
    the site. Disabled: not part of the form."""
    widget = get_rich_text_editor_widget(features=features)
    widget.options = {**widget.options, "readOnly": True, "topToolbar": None}
    name = f"sbs-readonly-{uuid.uuid4().hex}"
    return widget.render(name, html, {"id": name, "disabled": True})
