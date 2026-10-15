from django.urls import include, path

urlpatterns = [
    path("admin/", include("wagtail.admin.urls")),
    path("commentail/", include("commentail.urls")),
]
