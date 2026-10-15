from typing import ClassVar

from django.db import models
from django.utils.translation import gettext_lazy as _
from wagtail.admin.panels import FieldPanel, Panel
from wagtail.models import Page


class HomePage(Page):
    template = "demo_home/home_page.html"
    introduction = models.TextField(
        default="Try the comment form below.", verbose_name=_("Introduction")
    )
    content_panels: ClassVar[list[Panel]] = [
        *Page.content_panels,
        FieldPanel("introduction"),
    ]


class Product(models.Model):
    """An ordinary Django model to demonstrate explicit object adapters."""

    site = models.ForeignKey("wagtailcore.Site", on_delete=models.CASCADE)
    title = models.CharField(max_length=120)
    visible = models.BooleanField(default=True)

    def __str__(self) -> str:
        return self.title
