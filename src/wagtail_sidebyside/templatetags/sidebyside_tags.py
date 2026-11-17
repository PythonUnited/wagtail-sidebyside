from django import template
from django.urls import reverse
from wagtail.documents import get_document_model
from wagtail.images import get_image_model

from ..fields import IMAGE
from ..use_cases.page_status import PageStatus
from ..use_cases.sync_tree import SyncTree
from ..use_cases.translate_page import TranslatePage

register = template.Library()


@register.inclusion_tag("sidebyside/includes/translation_bar.html")
def translation_bar(page, current_locale=None, mode="edit"):
    """Row with a button for the source page and one per translation with its
    status, the same in the page editor, the translation screen and the page
    explorer. page: the source page or one of its translations.
    mode "edit": buttons open the editor / translation screen;
    mode "explore": buttons open the explorer of that language."""
    if page is None or not page.pk:
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
            "url": url(source, reverse("wagtailadmin_pages:edit", args=[source.pk])),
            "current": current.pk == source.locale_id,
        }
    ]
    for status in PageStatus.for_page(source):
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
