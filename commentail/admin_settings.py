"""Permission-scoped editorial settings, rule interchange and object listings."""

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import (
    HttpRequest,
    HttpResponse,
    StreamingHttpResponse,
)
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.utils.translation import gettext as _
from wagtail.admin import messages
from wagtail.models import Site

from .forms import (
    DiscussionSettingsForm,
    RuleCsvImportForm,
    RuleForm,
    SitePermissionForm,
    SiteSettingsForm,
)
from .models import (
    Discussion,
    ModerationRule,
    SiteCommentSettings,
)
from .permissions import can, sites_for
from .rules_csv import export_rules, import_rules
from .validation import valid_identifier


def settings_view(
    request: HttpRequest, site_id: int, page_id: int | None = None
) -> HttpResponse:
    """Edit Site defaults or a writable Page discussion with a settings grant."""
    if not can(request.user, site_id, "settings"):
        return HttpResponse("Permission denied", status=403)
    site = get_object_or_404(Site, pk=site_id)
    if page_id is None:
        instance = SiteCommentSettings.objects.filter(
            site=site
        ).first() or SiteCommentSettings(site=site)
        form_class = SiteSettingsForm
    else:
        from wagtail.models import Page

        page = get_object_or_404(Page, pk=page_id).specific
        if not page.permissions_for_user(request.user).can_edit():
            raise PermissionDenied
        from .detection import has_comments

        if not has_comments(page, request):
            raise PermissionDenied
        instance = Discussion.objects.filter(
            site=site, page=page
        ).first() or Discussion(site=site, page=page)
        form_class = DiscussionSettingsForm
    form = form_class(
        request.POST if request.method == "POST" else None, instance=instance
    )
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect(request.path)
    return TemplateResponse(
        request,
        "commentail/admin/form.html",
        {
            "form": form,
            "title": _("Discussion settings") if page_id else _("Site settings"),
            "site": site,
        },
    )


def rules(request: HttpRequest) -> HttpResponse:
    """List project-wide rules with bounded results and persistent filters."""
    if not sites_for(request.user, "rules").exists():
        raise PermissionDenied
    if identifier := request.GET.get("id"):
        if not valid_identifier(identifier):
            return HttpResponse("Invalid rule identifier", status=400)
        rule = get_object_or_404(ModerationRule, pk=identifier)
        return redirect("commentail_admin:rule_edit", identifier=rule.pk)
    query = ModerationRule.objects.all()
    search = request.GET.get("q", "").strip()
    action = request.GET.get("action", "")
    enabled = request.GET.get("enabled", "")
    if search:
        query = query.filter(phrase__icontains=search)
    if action in ModerationRule.Action.values:
        query = query.filter(action=action)
    if enabled in ("0", "1"):
        query = query.filter(enabled=enabled == "1")
    page = Paginator(query.order_by("phrase", "pk"), 25).get_page(request.GET.get("p"))
    previous = request.GET.copy()
    previous["p"] = str(max(1, page.number - 1))
    following = request.GET.copy()
    following["p"] = str(page.number + 1)
    return TemplateResponse(
        request,
        "commentail/admin/rules.html",
        {
            "rules": page,
            "actions": ModerationRule.Action.choices,
            "search": search,
            "active_action": action,
            "active_enabled": enabled,
            "previous_query": previous.urlencode(),
            "next_query": following.urlencode(),
        },
    )


def rule_edit(request: HttpRequest, identifier: int | None = None) -> HttpResponse:
    """Create or update a project-wide rule only with a rules-management grant."""
    if not sites_for(request.user, "rules").exists():
        raise PermissionDenied
    instance = get_object_or_404(ModerationRule, pk=identifier) if identifier else None
    form = RuleForm(
        request.POST if request.method == "POST" else None, instance=instance
    )
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect("commentail_admin:rules")
    return TemplateResponse(
        request,
        "commentail/admin/form.html",
        {
            "form": form,
            "title": _("Edit rule") if instance else _("Add rule"),
            "back_url": "commentail_admin:rules",
            "back_label": _("Moderation rules"),
        },
    )


def access(request: HttpRequest) -> HttpResponse:
    """Edit Site/group grants for superusers; invalid identifiers never reach ORM."""
    if not request.user.is_superuser:
        raise PermissionDenied
    from .models import SiteGroupPermission

    if request.GET.get("id") and not valid_identifier(request.GET["id"]):
        return HttpResponse("Invalid permission identifier", status=400)

    instance = (
        get_object_or_404(SiteGroupPermission, pk=request.GET["id"])
        if request.GET.get("id")
        else None
    )
    form = SitePermissionForm(
        request.POST if request.method == "POST" else None, instance=instance
    )
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect("commentail_admin:access")
    return TemplateResponse(
        request,
        "commentail/admin/form.html",
        {
            "form": form,
            "title": _("Group access by site"),
            "permissions": SiteGroupPermission.objects.select_related("group", "site"),
        },
    )


def rules_export(request: HttpRequest) -> StreamingHttpResponse:
    if not sites_for(request.user, "rules").exists():
        raise PermissionDenied
    return StreamingHttpResponse(
        export_rules(),
        content_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="commentail-rules.csv"'},
    )


def rules_import(request: HttpRequest) -> HttpResponse:
    """Validate the bounded upload before atomically merging rules by phrase."""
    if not sites_for(request.user, "rules").exists():
        raise PermissionDenied
    form = RuleCsvImportForm(
        request.POST if request.method == "POST" else None,
        request.FILES if request.method == "POST" else None,
    )
    if request.method == "POST" and form.is_valid():
        try:
            result = import_rules(form.cleaned_data["file"])
        except ValidationError as error:
            form.add_error("file", error)
        else:
            messages.success(
                request,
                _(
                    "CSV imported: %(added)s added, %(updated)s updated, %(unchanged)s unchanged."
                )
                % {
                    "added": result.added,
                    "updated": result.updated,
                    "unchanged": result.unchanged,
                },
            )
            return redirect("commentail_admin:rules")
    return TemplateResponse(
        request, "commentail/admin/rules_import.html", {"form": form}
    )


def objects_list(request: HttpRequest) -> HttpResponse:
    """Existing non-Page discussions; Site settings grants bound every row."""
    sites = sites_for(request.user, "settings")
    if not sites.exists():
        raise PermissionDenied
    query = Discussion.objects.filter(site__in=sites, page__isnull=True).select_related(
        "site", "content_type"
    )
    if value := request.GET.get("q", "").strip():
        query = query.filter(
            Q(object_id__icontains=value) | Q(content_type__model__icontains=value)
        )
    if value := request.GET.get("site", ""):
        query = query.filter(site_id=value) if valid_identifier(value) else query.none()
    page = Paginator(
        query.order_by("site_id", "content_type_id", "object_id", "pk"), 25
    ).get_page(request.GET.get("p"))
    previous = request.GET.copy()
    previous["p"] = str(max(1, page.number - 1))
    following = request.GET.copy()
    following["p"] = str(page.number + 1)
    return TemplateResponse(
        request,
        "commentail/admin/objects.html",
        {
            "discussions": page,
            "sites": sites,
            "previous_query": previous.urlencode(),
            "next_query": following.urlencode(),
        },
    )


def object_settings(request: HttpRequest, identifier: int) -> HttpResponse:
    """Edit stored object settings under the administrative Site grant.

    Adapter failures return a neutral 503 and preserve settings; visitor access
    is deliberately independent from this administrative authorization."""
    discussion = get_object_or_404(
        Discussion.objects.select_related("site", "content_type"),
        pk=identifier,
        page__isnull=True,
    )
    if not can(request.user, discussion.site_id, "settings"):
        return HttpResponse(_("Permission denied"), status=403)
    # Administrative Site grant controls settings, independently of visitor access.
    # Unavailable adapters must preserve stored settings and show a neutral error.
    from .objects import ObjectAccessError, target_for

    try:
        target = target_for(discussion)
    except ObjectAccessError:
        return HttpResponse(_("Comments are unavailable."), status=503)
    form = DiscussionSettingsForm(
        request.POST if request.method == "POST" else None, instance=discussion
    )
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect(request.path)
    return TemplateResponse(
        request,
        "commentail/admin/form.html",
        {
            "form": form,
            "title": _("Discussion settings"),
            "site": discussion.site,
            "target_label": str(target),
            "objects_back": True,
        },
    )
