from wagtail.admin.panels import Panel

from .translators import get_translator


class MachineTranslationStatusPanel(Panel):
    """Settings > Translations: the translator backend's connection status and
    set-up help (its status_template), this month's usage and a button to test
    the connection."""

    class BoundPanel(Panel.BoundPanel):
        template_name = "sidebyside/panels/machine_translation_status.html"

        def get_context_data(self, parent_context=None):
            # Imported here: the use case imports the models, which import
            # this module.
            from .use_cases.machine_translate import MachineTranslate

            translator = get_translator()
            context = super().get_context_data(parent_context)
            context["translator"] = translator
            context["status"] = translator.status()
            context["usage"] = MachineTranslate.usage()
            return context
