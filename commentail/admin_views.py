"""Wagtail moderation views; all object queries are bounded by Site rights."""

from difflib import SequenceMatcher

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Exists, F, OuterRef, Q, QuerySet
from django.http import HttpRequest, HttpResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.html import format_html, format_html_join
from django.utils.safestring import SafeString
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST
from wagtail.admin import messages
from wagtail.models import Page, Site

from .forms import (
    DiscussionSettingsForm,
    RuleCsvImportForm,
    RuleForm,
    SitePermissionForm,
    SiteSettingsForm,
)
from .models import (
    Comment,
    CommentRevision,
    Discussion,
    MailJob,
    ModerationRule,
    SiteCommentSettings,
)
from .outbox import requeue
from .permissions import Capability, can, sites_for
from .rules_csv import export_rules, import_rules
from .services import DomainError, hide, moderate, moderate_revision, remove, restore


def _comments(request: HttpRequest) -> QuerySet[Comment]:
    return Comment.objects.filter(
        discussion__site__in=sites_for(request.user, "view")
    ).select_related("discussion__site", "discussion__page", "user")


def index(request: HttpRequest) -> HttpResponse:
    sites = sites_for(request.user, "view")
    settings_sites = sites_for(request.user, "settings")
    if (
        not sites.exists()
        and not settings_sites.exists()
        and not sites_for(request.user, "rules").exists()
    ):
        raise PermissionDenied
    query = _comments(request).annotate(
        pending_revision=Exists(
            CommentRevision.objects.filter(comment_id=OuterRef("pk"), status="pending")
        )
    )
    if value := request.GET.get("site"):
        query = (
            query.filter(discussion__site_id=value)
            if value.isdecimal()
            else query.none()
        )
    if value := request.GET.get("page"):
        query = (
            query.filter(discussion__page_id=value)
            if value.isdecimal()
            else query.none()
        )
    active_status = request.GET.get("status", "pending")
    if value := request.GET.get("q"):
        names = Q()
        for field in (get_user_model().USERNAME_FIELD, "first_name", "last_name"):
            if field in {item.name for item in get_user_model()._meta.fields}:
                names |= Q(**{f"user__{field}__icontains": value})
        query = query.filter(
            names
            | Q(text__icontains=value)
            | Q(guest_name__icontains=value)
            | Q(email__icontains=value)
            | Q(user__email__icontains=value)
        )
    for key, lookup in [
        ("from", "created_at__date__gte"),
        ("to", "created_at__date__lte"),
    ]:
        if value := request.GET.get(key):
            try:
                day = parse_date(value)
            except ValueError:
                day = None
            query = query.filter(**{lookup: day}) if day else query.none()
    status_tabs: list[dict[str, object]] = []
    for value, label in [
        ("pending", _("Pending")),
        ("published", _("Published")),
        ("rejected", _("Rejected")),
        ("", _("All statuses")),
    ]:
        subset = (
            query.filter(Q(status="pending") | Q(pending_revision=True))
            if value == "pending"
            else query.filter(status=value)
            if value
            else query
        )
        parameters = request.GET.copy()
        parameters["status"] = value
        parameters.pop("p", None)
        status_tabs.append(
            {
                "label": label,
                "count": subset.count(),
                "query": parameters.urlencode(),
                "active": active_status == value,
            }
        )
    if active_status == "pending":
        query = query.filter(Q(status="pending") | Q(pending_revision=True))
    elif active_status:
        query = query.filter(status=active_status)
    page = Paginator(query.order_by("-created_at", "-pk"), 30).get_page(
        request.GET.get("p")
    )
    moderate_sites = set(
        sites_for(request.user, "moderate").values_list("pk", flat=True)
    )
    for comment in page:
        comment.can_select = (
            comment.status == "pending" and comment.discussion.site_id in moderate_sites
        )
    previous = request.GET.copy()
    previous["p"] = str(max(1, page.number - 1))
    following = request.GET.copy()
    following["p"] = str(page.number + 1)
    return TemplateResponse(
        request,
        "commentail/admin/list.html",
        {
            "comments": page,
            "sites": sites,
            "settings_sites": settings_sites,
            "statuses": Comment.Status.choices,
            "active_status": active_status,
            "status_tabs": status_tabs,
            "pages": Page.objects.filter(discussion__site__in=sites)
            .distinct()
            .order_by("title"),
            "mail_allowed": sites.exists(),
            "rules_allowed": sites_for(request.user, "rules").exists(),
            "access_allowed": request.user.is_superuser,
            "can_bulk": sites_for(request.user, "moderate").exists(),
            "previous_query": previous.urlencode(),
            "next_query": following.urlencode(),
        },
    )


def _diff(original: str, proposed: str) -> tuple[SafeString, SafeString]:
    old: list[SafeString] = []
    new: list[SafeString] = []
    # Limit pathological diff work; full texts are still safely visible.
    matcher = SequenceMatcher(
        None, original.splitlines(keepends=True), proposed.splitlines(keepends=True)
    )
    for operation, a, b, c, d in matcher.get_opcodes():
        old.append(
            format_html(
                "<del>{}</del>" if operation != "equal" else "{}",
                "".join(matcher.a[a:b]),
            )
        )
        new.append(
            format_html(
                "<ins>{}</ins>" if operation != "equal" else "{}",
                "".join(matcher.b[c:d]),
            )
        )
    return format_html_join("", "{}", ((part,) for part in old)), format_html_join(
        "", "{}", ((part,) for part in new)
    )


def _mail_retry_allowed(job: MailJob, moderate_sites: set[int]) -> bool:
    return (
        job.status == "failed"
        and job.expires_at > timezone.now()
        and job.comment.discussion.site_id in moderate_sites
        and job.recipient.discussion.site_id in moderate_sites
    )


def detail(request: HttpRequest, identifier: int) -> HttpResponse:
    comment = get_object_or_404(_comments(request), pk=identifier)
    revision = comment.revisions.filter(status="pending").first()
    old, proposed = _diff(comment.text, revision.text) if revision else ("", "")
    site_id = comment.discussion.site_id
    jobs = MailJob.objects.filter(
        recipient=comment,
        status="failed",
        comment__discussion__site__in=sites_for(request.user, "view"),
    ).select_related("comment__discussion", "recipient__discussion")
    moderate_sites = set(
        sites_for(request.user, "moderate").values_list("pk", flat=True)
    )
    for job in jobs:
        job.can_retry = _mail_retry_allowed(job, moderate_sites)
    return TemplateResponse(
        request,
        "commentail/admin/detail.html",
        {
            "comment": comment,
            "revision": revision,
            "old": old,
            "proposed": proposed,
            "can_moderate": can(request.user, site_id, "moderate"),
            "can_configure": can(request.user, site_id, "settings"),
            "can_hide": can(request.user, site_id, "hide"),
            "can_delete": can(request.user, site_id, "delete"),
            "events": comment.events.select_related("actor").order_by("-created_at")[
                :100
            ],
            "jobs": jobs,
        },
    )


def _mutate(request: HttpRequest, comment: Comment) -> None:
    action = request.POST.get("action", "")
    capabilities: dict[str, Capability] = {
        "approve": "moderate",
        "reject": "moderate",
        "hide": "hide",
        "restore": "hide",
        "delete": "delete",
    }
    capability = capabilities.get(action)
    if capability is None:
        raise DomainError("Unknown action")
    if not can(request.user, comment.discussion.site_id, capability):
        raise PermissionDenied
    if action in {"approve", "reject"}:
        moderate(
            comment.pk,
            action,
            actor=request.user,
            reason=request.POST.get("reason", ""),
        )
    else:
        {"hide": hide, "restore": restore, "delete": remove}[action](
            comment.pk, actor=request.user
        )


@require_POST
def action(request: HttpRequest, identifier: int) -> HttpResponse:
    comment = get_object_or_404(_comments(request), pk=identifier)
    try:
        _mutate(request, comment)
    except PermissionDenied:
        return HttpResponse("Permission denied", status=403)
    except DomainError as exc:
        return HttpResponse(str(exc), status=400)
    return redirect("commentail_admin:detail", identifier=identifier)


@require_POST
@transaction.atomic
def bulk(request: HttpRequest) -> HttpResponse:
    identifiers = request.POST.getlist("ids")
    if (
        not identifiers
        or len(identifiers) > 100
        or not all(value.isdecimal() for value in identifiers)
        or request.POST.get("action") not in {"approve", "reject"}
    ):
        return HttpResponse("Invalid selection", status=400)
    try:
        # Acquire the writer lock before dependent reads on SQLite as well.
        Comment.objects.filter(pk__in=identifiers).update(edit_locked=F("edit_locked"))
        for identifier in sorted(set(identifiers), key=int):
            comment = get_object_or_404(_comments(request), pk=identifier)
            _mutate(request, comment)
    except (DomainError, PermissionDenied) as exc:
        transaction.set_rollback(True)
        return HttpResponse(
            str(exc), status=403 if isinstance(exc, PermissionDenied) else 400
        )
    return redirect("commentail_admin:list")


@require_POST
def revision_action(request: HttpRequest, identifier: int) -> HttpResponse:
    if not request.POST.get("revision", "").isdecimal() or request.POST.get(
        "action"
    ) not in {"approve", "reject"}:
        return HttpResponse("Invalid revision action", status=400)
    comment = get_object_or_404(_comments(request), pk=identifier)
    if not can(request.user, comment.discussion.site_id, "moderate"):
        raise PermissionDenied
    revision = get_object_or_404(
        comment.revisions, pk=request.POST.get("revision"), status="pending"
    )
    try:
        moderate_revision(
            revision.pk,
            request.POST.get("action"),
            actor=request.user,
            reason=request.POST.get("reason", ""),
        )
    except DomainError as exc:
        return HttpResponse(str(exc), status=400)
    return redirect("commentail_admin:detail", identifier=identifier)


def settings_view(
    request: HttpRequest, site_id: int, page_id: int | None = None
) -> HttpResponse:
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
        if not identifier.isdecimal():
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
    if not request.user.is_superuser:
        raise PermissionDenied
    from .models import SiteGroupPermission

    if request.GET.get("id") and not request.GET["id"].isdecimal():
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


@require_POST
def retry_mail(request: HttpRequest, identifier: int) -> HttpResponse:
    job = get_object_or_404(
        MailJob.objects.filter(
            recipient__discussion__site__in=sites_for(request.user, "view"),
            comment__discussion__site__in=sites_for(request.user, "view"),
        ),
        pk=identifier,
    )
    try:
        requeue(job.pk, actor=request.user)
    except DomainError as exc:
        return HttpResponse(str(exc), status=400)
    if request.POST.get("return_to") == "mail":
        return redirect("commentail_admin:mail")
    return redirect("commentail_admin:detail", identifier=job.recipient_id)


def rules_export(request: HttpRequest) -> StreamingHttpResponse:
    if not sites_for(request.user, "rules").exists():
        raise PermissionDenied
    return StreamingHttpResponse(
        export_rules(),
        content_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="commentail-rules.csv"'},
    )


def rules_import(request: HttpRequest) -> HttpResponse:
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


def mail_queue(request: HttpRequest) -> HttpResponse:
    """Inspect delivery metadata only within both source and recipient Site grants."""
    sites = sites_for(request.user, "view")
    if not sites.exists():
        raise PermissionDenied
    statuses = (
        ("failed", _("Failed")),
        ("pending", _("Pending delivery")),
        ("sending", _("Sending")),
        ("sent", _("Sent")),
        ("cancelled", _("Cancelled")),
    )
    active_status = request.GET.get("status", "failed")
    query = MailJob.objects.filter(
        comment__discussion__site__in=sites, recipient__discussion__site__in=sites
    ).select_related(
        "recipient__discussion__site",
        "recipient__discussion__page",
        "recipient__user",
        "comment__discussion__site",
    )
    if active_status in dict(statuses):
        query = query.filter(status=active_status)
    selected_site = request.GET.get("site", "")
    if selected_site:
        query = (
            query.filter(recipient__discussion__site_id=selected_site)
            if selected_site.isdecimal()
            else query.none()
        )
    page = Paginator(query.order_by("-created_at", "-pk"), 25).get_page(
        request.GET.get("p")
    )
    moderate_sites = set(
        sites_for(request.user, "moderate").values_list("pk", flat=True)
    )
    kinds = {
        "confirm": _("Email confirmation"),
        "edit": _("Guest edit link"),
        "reply": _("Reply notification"),
        "published": _("Publication notification"),
        "rejected": _("Rejection notification"),
    }
    for job in page:
        job.can_retry = _mail_retry_allowed(job, moderate_sites)
        job.status_label = dict(statuses).get(job.status, job.status)
        job.kind_label = kinds.get(job.kind, job.kind)
    previous = request.GET.copy()
    previous["p"] = str(max(1, page.number - 1))
    following = request.GET.copy()
    following["p"] = str(page.number + 1)
    return TemplateResponse(
        request,
        "commentail/admin/mail.html",
        {
            "jobs": page,
            "sites": sites,
            "statuses": statuses,
            "active_status": active_status,
            "previous_query": previous.urlencode(),
            "next_query": following.urlencode(),
        },
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
        query = query.filter(site_id=value) if value.isdecimal() else query.none()
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
