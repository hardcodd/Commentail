from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404
from django.template.response import TemplateResponse
from wagtail.models import Site

from .models import Product


def product(request: HttpRequest, identifier: int) -> HttpResponse:
    obj = get_object_or_404(
        Product, pk=identifier, site=Site.find_for_request(request), visible=True
    )
    return TemplateResponse(request, "demo_home/product.html", {"product": obj})
