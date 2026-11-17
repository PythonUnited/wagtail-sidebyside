from django.db import models
from wagtail import blocks
from wagtail.admin.panels import FieldPanel
from wagtail.fields import StreamField
from wagtail.images.blocks import ImageChooserBlock
from wagtail.models import Page


class ImageBlock(blocks.StructBlock):
    image = ImageChooserBlock()
    caption = blocks.CharBlock(required=False)


class ChartBlock(blocks.StructBlock):
    """A block without text: always copied from the source."""

    date = blocks.DateBlock(required=False)

    class Meta:
        template = "testapp/chart_block.html"


class ContentBlocks(blocks.StreamBlock):
    heading = blocks.CharBlock()
    paragraph = blocks.TextBlock()
    rich_text = blocks.RichTextBlock()
    quote = blocks.BlockQuoteBlock()
    image = ImageBlock()
    chart = ChartBlock()


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
