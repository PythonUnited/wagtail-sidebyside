import html

from django.core.management.base import BaseCommand, CommandError
from django.utils.html import strip_tags

from ...fields import page_texts


class Command(BaseCommand):
    help = (
        "Run once before removing wagtail-localize. wagtail-localize only writes "
        "translations into the page when they are published. This saves the "
        "pages that have translations waiting in wagtail-localize as a draft, "
        "so the side-by-side screen shows them. Live pages are not changed."
    )

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        try:
            from wagtail_localize.models import Translation
        except ImportError as error:
            raise CommandError(
                "wagtail-localize is not installed (anymore): nothing to import."
            ) from error

        for translation in Translation.objects.select_related(
            "source", "target_locale"
        ):
            target = translation.get_target_instance()
            pending = _pending(translation, target)
            if not pending:
                continue
            self.stdout.write(
                f"[{translation.target_locale.language_code}] {target.pk} "
                f"{target.title}: {pending} translations waiting"
            )
            if not options["dry_run"]:
                translation.save_target(publish=False)


def _pending(translation, target) -> int:
    """Translations in wagtail-localize whose text is not in the page."""
    from wagtail_localize.models import StringSegment, StringTranslation

    texts = _plain(
        " ".join(page_texts(target.get_latest_revision_as_object()).values())
    )
    count = 0
    for segment in StringSegment.objects.filter(source=translation.source):
        string_translation = StringTranslation.objects.filter(
            translation_of_id=segment.string_id,
            context_id=segment.context_id,
            locale=translation.target_locale,
        ).first()
        # Compare without tags: wagtail-localize stores links as <a id="a1">.
        if string_translation and _plain(string_translation.data) not in texts:
            count += 1
    return count


def _plain(text: str) -> str:
    return " ".join(html.unescape(strip_tags(text)).split())
