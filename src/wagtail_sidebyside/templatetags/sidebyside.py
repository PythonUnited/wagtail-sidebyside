from django import template

from ..use_cases.page_status import HeadLinks

register = template.Library()


@register.inclusion_tag("sidebyside/head.html", takes_context=True)
def sidebyside_head(context, page=None):
    """In the <head> of the site's base template: {% sidebyside_head %}.
    Renders the canonical link and the hreflang alternates of the page."""
    page = page or context.get("page")
    if page is None or not getattr(page, "translation_key", None):
        return {}
    return HeadLinks.for_page(page, context.get("request"))
