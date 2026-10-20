"""Shared presentation for the permission-scoped Commentail administration."""

from django import template
from django.forms import BoundField
from django.forms.forms import BaseForm
from django.http import HttpRequest
from django.template import Context
from django.utils.translation import gettext as _

from commentail.forms import (
    DiscussionSettingsForm,
    SitePermissionForm,
    SiteSettingsForm,
)
from commentail.permissions import sites_for

register = template.Library()


@register.inclusion_tag("commentail/admin/management.html", takes_context=True)
def commentail_management(context: Context) -> dict[str, object]:
    """Offer the same authorized destinations on every Commentail admin page."""
    request: HttpRequest = context["request"]
    view_allowed = sites_for(request.user, "view").exists()
    return {
        "settings_sites": sites_for(request.user, "settings"),
        "mail_allowed": view_allowed,
        "rules_allowed": sites_for(request.user, "rules").exists(),
        "access_allowed": request.user.is_superuser,
    }


@register.simple_tag
def commentail_form_groups(form: BaseForm) -> list[tuple[str, list[BoundField]]]:
    """Group bound fields without replacing their widgets or validation state."""
    if isinstance(form, (SiteSettingsForm, DiscussionSettingsForm)):
        layout = [
            (_("Discussion settings"), ("mode", "moderation", "access", "max_length")),
            (_("Appearance"), ("highlight_staff", "clickable_links")),
            (_("Email delivery"), ("email_enabled", "notify_publication", "notify_rejection")),
        ]
    elif isinstance(form, SitePermissionForm):
        layout = [
            (_("Group access"), ("group", "site")),
            (_("Moderation"), ("view", "moderate", "hide", "delete")),
            (_("Management"), ("settings", "rules")),
        ]
    else:
        layout = [("", tuple(form.fields))]
    return [(title, [form[name] for name in names if name in form.fields])
            for title, names in layout]
