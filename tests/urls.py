from django.urls import include, path
from wagtail import urls as wagtail_urls

urlpatterns = [
    path("admin/", include("wagtail.admin.urls")),
    path("commentail/", include("commentail.urls")),
    path("", include(wagtail_urls)),
]
