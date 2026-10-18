"""Host URL configuration with Commentail mounted below a non-default prefix."""

from django.urls import include, path
from wagtail import urls as wagtail_urls

urlpatterns = [
    path("community/feedback/", include("commentail.urls")),
    path("", include(wagtail_urls)),
]
