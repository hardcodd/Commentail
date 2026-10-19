from django.http import HttpRequest
from django.urls import URLResolver, include, path, reverse
from django.utils.translation import gettext_lazy as _
from wagtail import hooks
from wagtail.admin.menu import MenuItem

from .group_permissions import (
    BaseGroupCommentPermissionFormSet,
    GroupCommentPermissionFormSet,
)
from .permissions import sites_for


@hooks.register("register_group_permission_panel")
def register_comment_permissions_panel() -> type[BaseGroupCommentPermissionFormSet]:
    return GroupCommentPermissionFormSet


class CommentsMenuItem(MenuItem):
    def is_shown(self, request: HttpRequest) -> bool:
        return any(
            sites_for(request.user, capability).exists()
            for capability in ("view", "settings", "rules")
        )


@hooks.register("register_admin_urls")
def register_urls() -> list[URLResolver]:
    return [path("commentail/", include("commentail.admin_urls"))]


@hooks.register("register_admin_menu_item")
def register_menu() -> MenuItem:
    return CommentsMenuItem(
        _("Comments"), reverse("commentail_admin:list"), icon_name="comment", order=600
    )


# Import registers the version-pinned page editor hooks.

from .page_integration import before_create, before_edit

hooks.register("before_edit_page", before_edit)
hooks.register("before_create_page", before_create)
