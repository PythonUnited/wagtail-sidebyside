from django.apps import AppConfig


class SideBySideConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "wagtail_sidebyside"
    label = "sidebyside"
    verbose_name = "Side-by-side translations"

    def ready(self):
        from . import signals

        signals.connect()
