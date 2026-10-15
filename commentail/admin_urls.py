from django.urls import path

from . import admin_views as views

app_name = "commentail_admin"
urlpatterns = [
    path("objects/", views.objects_list, name="objects"),
    path("objects/<int:identifier>/", views.object_settings, name="object_settings"),
    path("", views.index, name="list"),
    path("bulk/", views.bulk, name="bulk"),
    path("rules/", views.rules, name="rules"),
    path("rules/import/", views.rules_import, name="rules_import"),
    path("rules/export/", views.rules_export, name="rules_export"),
    path("rules/add/", views.rule_edit, name="rule_add"),
    path("rules/<int:identifier>/", views.rule_edit, name="rule_edit"),
    path("access/", views.access, name="access"),
    path("settings/<int:site_id>/", views.settings_view, name="settings"),
    path(
        "settings/<int:site_id>/<int:page_id>/",
        views.settings_view,
        name="page_settings",
    ),
    path("mail/", views.mail_queue, name="mail"),
    path("mail/<int:identifier>/retry/", views.retry_mail, name="retry"),
    path("<int:identifier>/", views.detail, name="detail"),
    path("<int:identifier>/action/", views.action, name="action"),
    path("<int:identifier>/revision/", views.revision_action, name="revision"),
]
