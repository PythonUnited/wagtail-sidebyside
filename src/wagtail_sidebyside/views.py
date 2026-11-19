from django.contrib.admin.utils import unquote
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.text import capfirst
from django.utils.translation import gettext as _
from django.utils.translation import ngettext
from wagtail import hooks
from wagtail.admin import messages
from wagtail.admin.action_menu import PageActionMenu
from wagtail.admin.rich_text import get_rich_text_editor_widget
from wagtail.admin.ui.components import MediaContainer
from wagtail.admin.ui.side_panels import (
    ChecksSidePanel,
    PageStatusSidePanel,
    PreviewSidePanel,
)
from wagtail.admin.views.generic.preview import PreviewOnEdit
from wagtail.models import Locale, Page
from wagtail.snippets.action_menu import SnippetActionMenu

from . import action_menu as footer_actions
from . import objects
from .conf import source_locale
from .forms import COPIED_PREFIX, TranslationForm
from .translators import TranslationError
from .use_cases.machine_translate import MachineTranslate
from .use_cases.page_status import PageStatus
from .use_cases.sync_tree import SyncTree
from .use_cases.translate_page import TranslatePage


def overview(request):
    """All source pages and snippets with their translation status per
    language."""
    show = request.GET.get("show", "all")
    return TemplateResponse(
        request,
        "sidebyside/overview.html",
        {
            "sections": PageStatus.overview(show),
            "locales": Locale.objects.exclude(pk=source_locale().id),
            "show": show,
            "filters": [
                ("all", _("All")),
                ("work", _("Needs work")),
                # Needs work, without the translations that were not started.
                ("started", _("In progress")),
            ],
        },
    )


def translate(request, page_id, locale_code):
    """Side-by-side translation of source page page_id into locale_code."""
    source_page = get_object_or_404(Page, pk=page_id).specific
    return _translate(request, source_page, locale_code)


def translate_snippet(request, app_label, model_name, pk, locale_code):
    """Side-by-side translation of a source snippet into locale_code."""
    source = objects.get_snippet(app_label, model_name, unquote(pk))
    return _translate(request, source, locale_code)


def _translate(request, source_page, locale_code):
    """source_page: a (specific) source page or snippet."""
    locale = get_object_or_404(Locale, language_code=locale_code)
    target_page = source_page.get_translation_or_none(locale)
    if target_page is None:
        return _create(request, source_page, locale)

    target_page = objects.specific(target_page)
    if not objects.can(request.user, target_page, "change"):
        raise PermissionDenied
    lock = objects.lock(target_page)
    locked = bool(lock and lock.for_user(request.user))

    source = objects.latest(source_page)
    target = objects.latest(target_page)
    rows = TranslatePage.rows(source, target)
    form = TranslationForm(rows, request.POST if request.method == "POST" else None)
    ai_available = MachineTranslate.available() and not locked
    focus = ""

    if request.method == "POST" and "discard" in request.POST:
        TranslatePage.discard_removed(target_page, int(request.POST["discard"]))
        return redirect(request.path)
    if request.method == "POST" and not locked and "copy" in request.POST:
        # Copy the source text into the field as a start, e.g. long rich text
        # with links and images. Shown, not saved.
        focus = request.POST["copy"]
        sources = {row.unit.path: row.unit.source for row in rows}
        if form.is_valid() and focus in sources:
            form = form.with_translations({focus: sources[focus]}, COPIED_PREFIX)
    elif request.method == "POST" and "ai" in request.POST:
        if ai_available and form.is_valid():
            focus = request.POST["ai"]
            form = _machine_translate(request, form, rows, focus, source_page, locale)
    elif request.method == "POST" and not locked and form.is_valid():
        publish = "action-publish" in request.POST
        together = "action-publish-together" in request.POST
        if (publish or together) and not objects.can(
            request.user, target_page, "publish"
        ):
            raise PermissionDenied
        if together and not objects.can(request.user, source_page, "publish"):
            raise PermissionDenied
        # A translation is never ahead of its source: with a newer source
        # draft, it is published against the published source (source_page,
        # loaded from the database, is the live version).
        source_pending = objects.has_unpublished_changes(source_page)
        if publish and source_pending and not source_page.live:
            messages.error(
                request,
                _("The source page is not published yet. Publish both together."),
            )
            return redirect(request.path)
        for fn in hooks.get_hooks("sidebyside_before_save_translation"):
            response = fn(request, source_page, target_page)
            if hasattr(response, "status_code"):
                return response
        try:
            revision = TranslatePage.save(
                source,
                target,
                rows,
                form.values(),
                form.changed_paths(),
                form.confirmed_paths(),
                form.machine_paths(),
                request.user,
                publish,
                same=frozenset(form.same_paths()),
                copied=frozenset(form.copied_paths()),
                live_source=source_page if publish and source_pending else None,
                awaiting_source=together,
            )
            if together:
                # Publishes the translation too (SyncTree.propagate).
                source_page.get_latest_revision().publish(user=request.user)
        except ValidationError as error:
            for field, errors in error.message_dict.items():
                form.add_error(field if field in form.fields else None, errors)
        else:
            for fn in hooks.get_hooks("sidebyside_after_save_translation"):
                response = fn(request, source_page, target_page, revision)
                if hasattr(response, "status_code"):
                    return response
            if together:
                messages.success(request, _("Source and translation published."))
            elif publish and source_pending:
                messages.success(
                    request,
                    _(
                        "Translation published. What it takes over from the "
                        "source's unpublished changes follows when the source "
                        "is published."
                    ),
                )
            elif publish:
                messages.success(request, _("Translation published."))
            elif objects.has_drafts(target_page):
                messages.success(request, _("Translation saved as draft."))
            else:
                messages.success(request, _("Translation saved."))
            return redirect(request.path)

    action_menu = _action_menu(request, target_page, lock, locked)
    footer_actions.adapt(action_menu, source_page, request.user)
    done, total = TranslatePage.progress(rows)
    orphans = TranslatePage.orphans(source, target)
    history_url = None
    if objects.can_view_history(request.user, target_page):
        history_url = objects.history_url(target_page)
    return TemplateResponse(
        request,
        "sidebyside/translate.html",
        {
            "source_page": source_page,
            "target_page": target_page,
            "is_page": objects.is_page(target_page),
            "title": objects.title(target_page),
            "breadcrumbs_items": _breadcrumbs(target_page),
            "source_pending": objects.has_unpublished_changes(source_page),
            "locale": locale,
            "form": form,
            # The editor also for the read-only rich text of the source.
            "media": form.media + get_rich_text_editor_widget().media,
            "done": done,
            "total": total,
            "counts": {
                status: sum(row.status == status for row in rows)
                for status in ("todo", "outdated", "review")
            },
            "action_menu": action_menu,
            "side_panels": _side_panels(request, source_page, target_page, locale),
            "history_url": history_url,
            "ai_available": ai_available,
            "ai_budget_reached": MachineTranslate.configured()
            and MachineTranslate.budget_reached(),
            "orphans": orphans,
            "removed": TranslatePage.removed(target_page),
            "focus": focus,
            "locked": locked,
        },
    )


def _machine_translate(request, form, rows, which, source_page, locale):
    """Machine translate one path, or with which="all" every empty field, and
    return a form showing the result. Nothing is saved."""
    values = form.values()
    if which == "all":
        # The slug follows the translated title instead.
        paths = {
            path
            for path, value in values.items()
            if not value and path != "slug" and path not in form.same_paths()
        }
    else:
        paths = {which}
    try:
        translations = MachineTranslate.translate(
            rows, paths, source_page.locale.language_code, locale.language_code
        )
    except TranslationError as error:
        messages.error(request, str(error))
        return form
    if not translations:
        messages.warning(request, _("Nothing to translate."))
        return form
    messages.success(
        request,
        ngettext(
            "%(count)s field translated by AI. Check it, then save.",
            "%(count)s fields translated by AI. Check them, then save.",
            len(translations),
        )
        % {"count": len(translations)},
    )
    return form.with_translations(translations)


def _breadcrumbs(target):
    """A snippet's header (a page has its own): listing > snippet."""
    if objects.is_page(target):
        return None
    return [
        {
            "url": objects.listing_url(target),
            "label": capfirst(target._meta.verbose_name_plural),
        },
        {"url": "", "label": objects.title(target)},
    ]


def _action_menu(request, target, lock, locked):
    """Wagtail's own action menu of the page or snippet editor."""
    if objects.is_page(target):
        return PageActionMenu(
            request, view="edit", page=target, lock=lock, locked_for_user=locked
        )
    return SnippetActionMenu(
        request, view="edit", instance=target, locked_for_user=locked
    )


def _side_panels(request, source_page, target_page, locale):
    """Wagtail's own side panels of the editor: status (pages), live preview
    and checks. Comments are left out: they belong to Wagtail's edit form."""
    panels = []
    if objects.is_previewable(target_page):
        preview_url = objects.preview_url(source_page, locale)
        panels.append(PreviewSidePanel(target_page, request, preview_url=preview_url))
        panels.append(ChecksSidePanel(target_page, request))
    if not objects.is_page(target_page):
        return MediaContainer(panels)
    panels.insert(
        0,
        PageStatusSidePanel(
            target_page,
            request,
            show_schedule_publishing_toggle=False,
            live_object=target_page,
            locale=locale,
            translations=[
                {
                    "locale": page.locale,
                    "url": reverse("wagtailadmin_pages:edit", args=[page.pk]),
                }
                for page in target_page.get_translations().select_related("locale")
            ],
            parent_page=target_page.get_parent(),
        ),
    )
    return MediaContainer(panels)


class TranslationPreview(PreviewOnEdit):
    """Wagtail's live preview, fed by the translation form instead of the
    edit form: shows the translation as it would be saved."""

    def get_source(self):
        if "page_id" in self.kwargs:
            return get_object_or_404(Page, pk=self.kwargs["page_id"]).specific
        return objects.get_snippet(
            self.kwargs["app_label"],
            self.kwargs["model_name"],
            unquote(self.kwargs["pk"]),
        )

    def get_object(self):
        source = self.get_source()
        locale = get_object_or_404(Locale, language_code=self.kwargs["locale_code"])
        target = source.get_translation_or_none(locale)
        if target is None:
            raise Http404
        target = objects.specific(target)
        if not objects.can(self.request.user, target, "change"):
            raise PermissionDenied
        self.source = objects.latest(source)
        return objects.latest(target)

    def get_form(self, query_dict):
        return _PreviewForm(self.source, self.object, query_dict)


class _PreviewForm:
    """The part of a model form that PreviewOnEditView uses."""

    def __init__(self, source, target, data):
        self.source = source
        self.target = target
        self.data = data
        self.rows = TranslatePage.rows(source, target)
        self.form = TranslationForm(self.rows, data)

    def is_valid(self):
        return self.form.is_valid()

    def save(self, commit=False):
        return TranslatePage.preview(
            self.source,
            self.target,
            self.rows,
            self.form.values(),
            self.form.same_paths(),
        )


def ai_check(request):
    """Settings > Translations, "Test connection"."""
    if request.method != "POST" or not request.user.has_perm(
        "sidebyside.change_translationsettings"
    ):
        raise PermissionDenied
    try:
        MachineTranslate.check()
    except TranslationError as error:
        messages.error(request, str(error))
    else:
        messages.success(
            request,
            _("Connection works."),
        )
    return redirect("wagtailsettings:edit", "sidebyside", "translationsettings")


def _create(request, source_page, locale):
    if not objects.can(request.user, source_page, "change"):
        raise PermissionDenied
    if request.method == "POST":
        SyncTree.create_translations(source_page, request.user)
        return redirect(request.path)
    return TemplateResponse(
        request,
        "sidebyside/create.html",
        {
            "source_page": source_page,
            "title": objects.title(source_page),
            "locale": locale,
        },
    )
