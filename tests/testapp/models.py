from django.db import models
from wagtail import blocks
from wagtail.admin.panels import FieldPanel
from wagtail.contrib.typed_table_block.blocks import TypedTableBlock
from wagtail.fields import RichTextField, StreamField
from wagtail.images.blocks import ImageChooserBlock
from wagtail.models import (
    DraftStateMixin,
    LockableMixin,
    Page,
    RevisionMixin,
    TranslatableMixin,
)
from wagtail.snippets.models import register_snippet


class ImageBlock(blocks.StructBlock):
    image = ImageChooserBlock()
    caption = blocks.CharBlock(required=False)


class ChartBlock(blocks.StructBlock):
    """A block without text: always copied from the source."""

    date = blocks.DateBlock(required=False)

    class Meta:
        template = "testapp/chart_block.html"


class TableBlock(TypedTableBlock):
    text = blocks.CharBlock()
    image = ImageChooserBlock()


class ContentBlocks(blocks.StreamBlock):
    heading = blocks.CharBlock()
    paragraph = blocks.TextBlock()
    rich_text = blocks.RichTextBlock()
    quote = blocks.BlockQuoteBlock()
    image = ImageBlock()
    chart = ChartBlock()
    table = TableBlock()


class Body(ContentBlocks):
    columns = blocks.StructBlock([("columns", blocks.ListBlock(ContentBlocks()))])


class TestPage(Page):
    hero_title = models.CharField(max_length=255, blank=True)
    header_image = models.ForeignKey(
        "wagtailimages.Image",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    theme = models.CharField(
        max_length=20,
        choices=[("blue", "Blue"), ("teal", "Teal"), ("night", "Night")],
        default="blue",
    )
    body = StreamField(Body, blank=True)

    # Always taken from the source page.
    translation_exclude = ["header_image"]

    content_panels = Page.content_panels + [
        FieldPanel("hero_title"),
        FieldPanel("header_image"),
        FieldPanel("theme"),
        FieldPanel("body"),
    ]


@register_snippet
class Footer(TranslatableMixin, models.Model):
    """A snippet without drafts: saved is live."""

    heading = models.CharField(max_length=255)
    text = RichTextField(blank=True)
    colour = models.CharField(
        max_length=20, choices=[("dark", "Dark"), ("light", "Light")], default="dark"
    )

    class Meta(TranslatableMixin.Meta):
        pass

    def __str__(self):
        return self.heading


@register_snippet
class Notice(
    TranslatableMixin, DraftStateMixin, RevisionMixin, LockableMixin, models.Model
):
    """A snippet with drafts and revisions."""

    text = models.CharField(max_length=255)
    body = StreamField(ContentBlocks, blank=True)

    class Meta(TranslatableMixin.Meta):
        pass

    def __str__(self):
        return self.text
