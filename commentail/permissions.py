"""Site capabilities used consistently by menus, queries and mutations."""

from typing import Literal

from django.contrib.auth.models import AbstractBaseUser
from django.db.models import QuerySet
from wagtail.models import Site

from .models import SiteGroupPermission

Capability = Literal["view", "moderate", "hide", "delete", "settings", "rules"]


def sites_for(user: AbstractBaseUser, capability: Capability) -> QuerySet[Site]:
    if (
        not user.is_authenticated
        or not user.is_active
        or not user.has_perm("wagtailadmin.access_admin")
    ):
        return Site.objects.none()
    if user.is_superuser:
        return Site.objects.all()
    return Site.objects.filter(
        pk__in=SiteGroupPermission.objects.filter(
            group__user=user, **{capability: True}
        ).values("site_id")
    )


def can(user: AbstractBaseUser, site_id: int, capability: Capability) -> bool:
    return sites_for(user, capability).filter(pk=site_id).exists()
