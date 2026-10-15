"""Minimal adapter: one Site per object and public visibility checked each time."""

from django.http import HttpRequest
from django.urls import reverse
from wagtail.models import Site

from .models import Product


class ProductAdapter:
    def get_site(self, obj: Product, request: HttpRequest) -> Site:
        return obj.site

    def can_view(self, obj: Product, request: HttpRequest) -> bool:
        return obj.visible

    def get_url(self, obj: Product, site: Site) -> str:
        return reverse("demo_product", args=[obj.pk])
