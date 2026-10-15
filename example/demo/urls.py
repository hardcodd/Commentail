from demo_home.views import product
from django.urls import include, path
from wagtail import urls as wagtail_urls

urlpatterns = [
    path("products/<int:identifier>/", product, name="demo_product"),
    path("admin/", include("wagtail.admin.urls")),
    path("commentail/", include("commentail.urls")),
    path("", include(wagtail_urls)),
]
