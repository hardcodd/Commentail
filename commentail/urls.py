from django.urls import path

from .public import discussion_view, edit_view, resend_view, submit_view
from .views import action

app_name = "commentail"
urlpatterns = [
    path("objects/<int:discussion_id>/", discussion_view, name="object_discussion"),
    path("objects/<int:discussion_id>/submit/", submit_view, name="object_submit"),
    path("discussions/<int:page_id>/", discussion_view, name="discussion"),
    path("discussions/<int:page_id>/submit/", submit_view, name="submit"),
    path("comments/<int:identifier>/edit/", edit_view, name="edit"),
    path("comments/<int:identifier>/resend/", resend_view, name="resend"),
    path("actions/<str:purpose>/", action, name="action"),
]
