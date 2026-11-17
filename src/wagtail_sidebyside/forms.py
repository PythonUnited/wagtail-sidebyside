from django import forms
from django.conf import settings
from django.utils.text import slugify
from wagtail.admin.rich_text import get_rich_text_editor_widget
from wagtail.documents import get_document_model
from wagtail.documents.widgets import AdminDocumentChooser
from wagtail.images import get_image_model
from wagtail.images.widgets import AdminImageChooser

from .fields import CHOOSER_KINDS, HTML, IMAGE, RICHTEXT, SYNCED, TEXTAREA

# Hidden inputs "machine:<path>" and "copied:<path>" carry a machine
# translation or a copied source text that is shown in the form but not saved
# yet, to tell whether the editor changed it.
MACHINE_PREFIX = "machine:"
COPIED_PREFIX = "copied:"


class TranslationForm(forms.Form):
    """One field per translatable unit, named by the unit path."""

    def __init__(self, rows, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.rows = rows
        for index, row in enumerate(rows):
            if row.unit.kind in CHOOSER_KINDS:
                self.fields[row.unit.path] = self._chooser_field(row)
            elif row.unit.kind != SYNCED:
                widget = self._widget(row.unit)
                # Paths contain dots, which break "#id" selectors (Draftail).
                widget.attrs["id"] = f"sbs-field-{index}"
                self.fields[row.unit.path] = forms.CharField(
                    required=False,
                    initial=row.translation,
                    label=row.unit.label,
                    widget=widget,
                )

    def entries(self):
        """(row, bound field or None, unsaved machine translation or None,
        unsaved copied source text or None), in page order."""
        machine = self._marked(MACHINE_PREFIX)
        copied = self._marked(COPIED_PREFIX)
        return [
            (
                row,
                self[row.unit.path] if row.unit.path in self.fields else None,
                machine.get(row.unit.path),
                copied.get(row.unit.path),
            )
            for row in self.rows
        ]

    def clean(self):
        data = super().clean()
        if not data.get("slug") and data.get("title"):
            allow_unicode = getattr(settings, "WAGTAIL_ALLOW_UNICODE_SLUGS", True)
            data["slug"] = slugify(data["title"], allow_unicode=allow_unicode)
        return data

    def values(self) -> dict[str, str]:
        """path -> text, or for an image/document the id of its own one (only
        when "Use a different ... in this language" is ticked)."""
        overrides = self.override_paths()
        values = {}
        for path, value in self.cleaned_data.items():
            if isinstance(self.fields[path], forms.ModelChoiceField):
                values[path] = str(value.pk) if value and path in overrides else ""
            else:
                values[path] = value.strip()
        return values

    def changed_paths(self) -> set[str]:
        """Paths whose text differs from what was shown. Rich text is compared
        after an editor round trip, which normalises the HTML."""
        values = self.values()
        return {
            path
            for path, field in self.fields.items()
            if not isinstance(field, forms.ModelChoiceField)
            and values[path] != self._normalise(path, field.initial)
        }

    def override_paths(self) -> set[str]:
        """Images/documents ticked "different in this language"."""
        if self.is_bound:
            return set(self.data.getlist("override"))
        return {row.unit.path for row in self.rows if row.override}

    def confirmed_paths(self) -> set[str]:
        return set(self.data.getlist("confirm"))

    def same_paths(self) -> set[str]:
        """Paths ticked "Same in both languages": as submitted, or as saved."""
        if self.is_bound:
            return set(self.data.getlist("same"))
        return {row.unit.path for row in self.rows if row.same}

    def machine_texts(self) -> dict[str, str]:
        return self._marked(MACHINE_PREFIX)

    def machine_paths(self) -> set[str]:
        """Paths still holding the unchanged machine translation."""
        return self._unchanged(MACHINE_PREFIX)

    def copied_paths(self) -> set[str]:
        """Paths still holding the unchanged copied source text."""
        return self._unchanged(COPIED_PREFIX)

    def with_translations(
        self, translations: dict[str, str], prefix: str = MACHINE_PREFIX
    ) -> "TranslationForm":
        """A new bound form with the submitted data plus these texts (machine
        translations, or with COPIED_PREFIX copied source texts), to show (not
        save) them."""
        data = self.data.copy()
        for path, text in translations.items():
            data[path] = self.fields[path].widget.format_value(text)
            data[prefix + path] = text
        return TranslationForm(self.rows, data)

    def _marked(self, prefix: str) -> dict[str, str]:
        return {
            key[len(prefix) :]: value
            for key, value in self.data.items()
            if key.startswith(prefix) and key[len(prefix) :] in self.fields
        }

    def _unchanged(self, prefix: str) -> set[str]:
        values = self.values()
        return {
            path
            for path, text in self._marked(prefix).items()
            if values[path] == self._normalise(path, text)
        }

    def _normalise(self, path, value: str) -> str:
        widget = self.fields[path].widget
        if value and hasattr(widget, "converter"):
            value = widget.value_from_datadict(
                {path: widget.format_value(value)}, {}, path
            )
        return (value or "").strip()

    @staticmethod
    def _chooser_field(row):
        """Wagtail's image/document chooser, starting at the translation's own
        object or else the source's."""
        if row.unit.kind == IMAGE:
            model, widget = get_image_model(), AdminImageChooser()
        else:
            model, widget = get_document_model(), AdminDocumentChooser()
        initial = row.translation or row.unit.source
        return forms.ModelChoiceField(
            queryset=model.objects.all(),
            required=False,
            initial=int(initial) if initial else None,
            label=row.unit.label,
            widget=widget,
        )

    @staticmethod
    def _widget(unit):
        if unit.kind == RICHTEXT:
            return get_rich_text_editor_widget(features=unit.features)
        if unit.kind == HTML:
            return forms.Textarea(attrs={"rows": 6, "class": "sbs-code"})
        if unit.kind == TEXTAREA:
            return forms.Textarea(attrs={"rows": 3})
        return forms.TextInput()
