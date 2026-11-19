from django.http import QueryDict
from django.shortcuts import redirect
from django.templatetags.static import static
from django.urls import include, path, reverse
from django.utils.html import format_html
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from wagtail import hooks
from wagtail.admin import messages
from wagtail.admin import widgets as wagtailadmin_widgets
from wagtail.admin.menu import MenuItem
from wagtail.admin.ui.components import Component
from wagtail.models import Locale, Page

from . import objects, views
from .conf import source_locale
from .use_cases.page_status import PageStatus
from .use_cases.sync_tree import SyncTree
from .use_cases.translate_page import TranslatePage


@hooks.register("register_admin_urls")
def register_admin_urls():
    urls = [
        path("", views.overview, name="overview"),
        path("<int:page_id>/<str:locale_code>/", views.translate, name="translate"),
        path("ai-check/", views.ai_check, name="ai_check"),
        path(
            "<int:page_id>/<str:locale_code>/preview/",
            views.TranslationPreview.as_view(),
            name="preview",
        ),
        path(
            "snippet/<str:app_label>/<str:model_name>/<str:pk>/<str:locale_code>/",
            views.translate_snippet,
            name="translate_snippet",
        ),
        path(
            "snippet/<str:app_label>/<str:model_name>/<str:pk>/<str:locale_code>/preview/",
            views.TranslationPreview.as_view(),
            name="preview_snippet",
        ),
    ]
    return [path("sidebyside/", include((urls, "sidebyside"), namespace="sidebyside"))]


@hooks.register("register_admin_menu_item")
def register_menu_item():
    return MenuItem(
        gettext_lazy("Translations"),
        reverse("sidebyside:overview"),
        icon_name="globe",
        order=250,
    )


@hooks.register("before_edit_page")
def redirect_translation_to_side_by_side(request, page):
    source = TranslatePage.source_of(page)
    if source is None:
        return None
    return redirect("sidebyside:translate", source.pk, page.locale.language_code)


@hooks.register("before_create_page")
def create_in_source_locale_only(request, parent_page, page_class):
    """Pages are created in the source tree only. Adding one in a translated
    tree continues under the source version of the parent instead."""
    locale = source_locale()
    if parent_page.is_root() or parent_page.locale_id == locale.id:
        return None
    language = {"language": locale.get_display_name()}
    source_parent = TranslatePage.source_of(parent_page)
    if source_parent is None:
        messages.error(
            request,
            _("Create pages in %(language)s. Translations are created automatically.")
            % language,
        )
        return redirect("wagtailadmin_explore", parent_page.pk)
    messages.info(
        request,
        _(
            "Pages are created in %(language)s, so you are now adding it there. "
            "The translation is created automatically."
        )
        % language,
    )
    return redirect(
        "wagtailadmin_pages:add",
        page_class._meta.app_label,
        page_class._meta.model_name,
        source_parent.pk,
    )


@hooks.register("after_create_page")
def create_translations(request, page):
    if SyncTree.is_source(page):
        SyncTree.create_translations(page, request.user)


def _refuse_fixed_translations(request, items):
    """A translation follows its source: moving or deleting it on its own
    would put the languages out of step. Refuse with a message."""
    fixed = SyncTree.fixed_translations(items)
    if not fixed:
        return None
    item, source = fixed[0]
    language = {"language": source.locale.get_display_name()}
    if objects.is_page(item):
        message = _(
            "'%(title)s' is a translation. Move or delete the %(language)s page "
            "instead: its translations follow."
        )
        button = _("Go to the %(language)s page") % language
    else:
        message = _(
            "'%(title)s' is a translation. Delete the %(language)s version "
            "instead: its translations follow."
        )
        button = _("Go to the %(language)s version") % language
    messages.error(
        request,
        message % {"title": objects.title(item), **language},
        buttons=[messages.button(objects.edit_url(source), button)],
    )
    return redirect(objects.listing_url(item))


@hooks.register("before_move_page")
def refuse_moving_translation(request, page, destination):
    return _refuse_fixed_translations(request, [page])


@hooks.register("before_delete_page")
def refuse_deleting_translation(request, page):
    return _refuse_fixed_translations(request, [page])


@hooks.register("before_bulk_action")
def refuse_bulk_move_or_delete_translations(
    request, action_type, objects, action_class_instance
):
    pages = [obj for obj in objects if isinstance(obj, Page)]
    if action_type in ("move", "delete") and pages:
        return _refuse_fixed_translations(request, pages)
    return None


@hooks.register("before_edit_snippet")
def redirect_snippet_translation_to_side_by_side(request, instance):
    if not objects.is_translatable_snippet(type(instance)):
        return None
    source = TranslatePage.source_of(instance)
    if source is None:
        return None
    return redirect(objects.translate_url(source, instance.locale))


@hooks.register("before_create_snippet")
def create_snippets_in_source_locale_only(request, model):
    """As pages: created in the source language, translations follow."""
    if not objects.is_translatable_snippet(model):
        return None
    locale = source_locale()
    code = request.GET.get("locale") or Locale.get_default().language_code
    if code == locale.language_code:
        return None
    messages.info(
        request,
        _(
            "This is created in %(language)s, so you are now adding it there. "
            "The translations are created automatically."
        )
        % {"language": locale.get_display_name()},
    )
    query = QueryDict(mutable=True)
    query.update(request.GET)
    query["locale"] = locale.language_code
    return redirect(f"{request.path}?{query.urlencode()}")


@hooks.register("before_delete_snippet")
def refuse_deleting_snippet_translation(request, instances):
    if not instances or not objects.is_translatable_snippet(type(instances[0])):
        return None
    return _refuse_fixed_translations(request, instances)


@hooks.register("register_snippet_listing_buttons")
def translate_snippet_listing_buttons(snippet, user, next_url=None):
    if not objects.is_translatable_snippet(type(snippet)):
        return
    if not SyncTree.is_source(snippet):
        return
    for locale in PageStatus.target_locales(snippet):
        yield wagtailadmin_widgets.Button(
            _("Translate: %(language)s") % {"language": locale.get_display_name()},
            objects.translate_url(snippet, locale),
            icon_name="globe",
            priority=60,
        )


@hooks.register("construct_translated_pages_to_cascade_actions")
def cascade_to_translations(pages, action):
    # Wagtail moves, deletes or unpublishes these along with the source page.
    return SyncTree.cascade(pages)


@hooks.register("register_page_header_buttons")
def translate_header_buttons(page, user, view_name, next_url=None):
    # The page editor shows them in a row of buttons instead, see
    # templates/wagtailadmin/pages/edit.html.
    if view_name == "edit" or not SyncTree.is_source(page):
        return
    for status in PageStatus.for_object(page):
        yield wagtailadmin_widgets.Button(
            f"{status.locale.get_display_name()}: {status.label}",
            status.url,
            icon_name="globe",
            priority=80,
        )


@hooks.register("register_page_listing_more_buttons")
def translate_listing_buttons(page, user, next_url=None):
    if not SyncTree.is_source(page):
        return
    for locale in PageStatus.target_locales(page):
        yield wagtailadmin_widgets.Button(
            _("Translate: %(language)s") % {"language": locale.get_display_name()},
            reverse("sidebyside:translate", args=[page.pk, locale.language_code]),
            icon_name="globe",
            priority=60,
        )


@hooks.register("after_publish_page")
def warn_about_translation_work(request, page):
    if not SyncTree.is_source(page):
        return
    for status in PageStatus.for_object(page):
        if status.target is not None and status.needs_work:
            messages.warning(
                request,
                _("%(language)s translation: %(status)s.")
                % {
                    "language": status.locale.get_display_name(),
                    "status": status.label,
                },
                buttons=[messages.button(status.url, _("Translate"))],
            )


class TranslationsPanel(Component):
    name = "sidebyside_translations"
    template_name = "sidebyside/dashboard_panel.html"
    order = 150

    def get_context_data(self, parent_context=None):
        sections = PageStatus.overview("work")
        return {"rows": [row for section in sections for row in section.rows]}


@hooks.register("construct_homepage_panels")
def add_translations_panel(request, panels):
    panels.append(TranslationsPanel())


@hooks.register("insert_global_admin_css")
def global_admin_css():
    return format_html(
        '<link rel="stylesheet" href="{}">',
        static("sidebyside/sidebyside.css"),
    )
