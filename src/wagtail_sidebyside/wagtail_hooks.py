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

from . import views
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
    for status in PageStatus.for_page(page):
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
    for status in PageStatus.for_page(page):
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
        return {"rows": PageStatus.overview(needs_work_only=True)}


@hooks.register("construct_homepage_panels")
def add_translations_panel(request, panels):
    panels.append(TranslationsPanel())


@hooks.register("insert_global_admin_css")
def global_admin_css():
    return format_html(
        '<link rel="stylesheet" href="{}">',
        static("sidebyside/sidebyside.css"),
    )
