"""TranslationState: a generic key (content type + object id) instead of a
page, so snippets have a state too. Existing states keep their page."""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from django.db.models.functions import Cast


def _page_type(apps):
    # Pages are stored as Page (see managers._key).
    ContentType = apps.get_model("contenttypes", "ContentType")
    return ContentType.objects.get_or_create(app_label="wagtailcore", model="page")[0]


def to_object(apps, schema_editor):
    TranslationState = apps.get_model("sidebyside", "TranslationState")
    TranslationState.objects.update(
        content_type=_page_type(apps),
        object_id=Cast("page_id", models.CharField(max_length=255)),
    )


def to_page(apps, schema_editor):
    TranslationState = apps.get_model("sidebyside", "TranslationState")
    states = TranslationState.objects.all()
    states.exclude(content_type=_page_type(apps)).delete()
    for state in states:
        state.page_id = int(state.object_id)
        state.save(update_fields=["page"])


class Migration(migrations.Migration):
    dependencies = [
        ("contenttypes", "0002_remove_content_type_name"),
        ("sidebyside", "0007_awaiting_source"),
    ]

    operations = [
        migrations.AddField(
            model_name="translationstate",
            name="content_type",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="+",
                to="contenttypes.contenttype",
            ),
        ),
        migrations.AddField(
            model_name="translationstate",
            name="object_id",
            field=models.CharField(default="", max_length=255),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name="translationstate",
            name="page",
            field=models.OneToOneField(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="+",
                to=settings.WAGTAIL_PAGE_MODEL,
            ),
        ),
        migrations.RunPython(to_object, to_page),
        migrations.RemoveField(model_name="translationstate", name="page"),
        migrations.AlterField(
            model_name="translationstate",
            name="content_type",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="+",
                to="contenttypes.contenttype",
            ),
        ),
        migrations.AddConstraint(
            model_name="translationstate",
            constraint=models.UniqueConstraint(
                fields=("content_type", "object_id"),
                name="sidebyside_translationstate_object",
            ),
        ),
    ]
