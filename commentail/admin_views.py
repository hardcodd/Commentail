"""Wagtail moderation views; all object queries are bounded by Site rights."""

from difflib import SequenceMatcher
from urllib.parse import urlencode

from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, F, Q
from django.http import (
    Http404,
    HttpRequest,
    HttpResponse,
    QueryDict,
)
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html, format_html_join
from django.utils.safestring import SafeString
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST
from wagtail.admin import messages
from wagtail.admin.widgets import AdminPageChooser
from wagtail.models import Page

from .admin_queries import _comments, filtered_comments
from .admin_settings import (
    access,
    object_settings,
    objects_list,
    rule_edit,
    rules,
    rules_export,
    rules_import,
    settings_view,
)
from .models import (
    Comment,
    CommentRevision,
    MailJob,
)
from .outbox import requeue
from .permissions import Capability, can, sites_for
from .services import DomainError, hide, moderate, moderate_revision, remove, restore
from .validation import valid_identifier

_ACTION_CAPABILITIES: dict[str, Capability] = {
    "approve": "moderate",
    "reject": "moderate",
    "hide": "hide",
    "restore": "hide",
    "delete": "delete",
}
_BULK_STATUSES = {
    "approve": {"pending"},
    "reject": {"pending"},
    "hide": {"published"},
    "restore": {"hidden"},
    "delete": set(Comment.Status.values) - {"deleted"},
}


def index(request: HttpRequest) -> HttpResponse:
    """Render the Site-scoped queue with filtered status totals and bulk eligibility."""
    sites = sites_for(request.user, "view")
    settings_sites = sites_for(request.user, "settings")
    if (
        not sites.exists()
        and not settings_sites.exists()
        and not sites_for(request.user, "rules").exists()
    ):
        raise PermissionDenied
    query = filtered_comments(request)
    active_status = request.GET.get("status", "pending")
    status_tabs: list[dict[str, object]] = []
    # An IN subquery can be hashed once by PostgreSQL; an EXISTS in this aggregate
    # would otherwise probe the revision index for every historical comment.
    pending = Q(status="pending") | Q(
        pk__in=CommentRevision.objects.filter(
            status="pending",
        ).values("comment_id")
    )
    totals = query.aggregate(
        pending=Count("pk", filter=pending),
        published=Count("pk", filter=Q(status="published")),
        rejected=Count("pk", filter=Q(status="rejected")),
        total=Count("pk"),
    )
    for value, label in [
        ("pending", _("Pending")),
        ("published", _("Published")),
        ("rejected", _("Rejected")),
        ("", _("All statuses")),
    ]:
        parameters = request.GET.copy()
        parameters["status"] = value
        parameters.pop("p", None)
        status_tabs.append(
            {
                "label": label,
                "count": totals[value or "total"],
                "query": parameters.urlencode(),
                "active": active_status == value,
            }
        )
    if active_status == "pending":
        query = query.filter(pending)
    elif active_status:
        query = query.filter(status=active_status)
    paginator = Paginator(query.order_by("-created_at", "-pk"), 30)
    if active_status in {"pending", "published", "rejected", ""}:
        paginator.count = totals[active_status or "total"]
    page = paginator.get_page(request.GET.get("p"))
    action_sites = {
        capability: set(
            sites_for(request.user, capability).values_list("pk", flat=True)
        )
        for capability in ("moderate", "hide", "delete")
    }
    available_actions: set[str] = set()
    for comment in page:
        actions = [
            action
            for action, capability in _ACTION_CAPABILITIES.items()
            if comment.status in _BULK_STATUSES[action]
            and comment.discussion.site_id in action_sites[capability]
        ]
        comment.bulk_actions = " ".join(actions)
        available_actions.update(actions)
    action_labels = {
        "approve": _("Approve"),
        "reject": _("Reject"),
        "hide": _("Hide"),
        "restore": _("Restore"),
        "delete": _("Erase text"),
    }
    action_help = {
        "approve": _(
            "Requires pending comments and moderation permission for every selected comment."
        ),
        "reject": _(
            "Requires pending comments and moderation permission for every selected comment."
        ),
        "hide": _(
            "Requires published comments and hide permission for every selected comment."
        ),
        "restore": _(
            "Requires hidden comments and hide permission for every selected comment."
        ),
        "delete": _(
            "Requires comments whose text has not been erased and delete permission for every selected comment."
        ),
    }
    previous = request.GET.copy()
    previous["p"] = str(max(1, page.number - 1))
    following = request.GET.copy()
    following["p"] = str(page.number + 1)
    selected_page = None
    if valid_identifier(identifier := request.GET.get("page", "")):
        selected_page = Page.objects.filter(
            pk=identifier,
            discussion__site__in=sites,
        ).first()
    page_chooser = AdminPageChooser()
    advanced_filter_count = sum(
        bool(request.GET.get(key)) for key in ("site", "page", "from", "to")
    )
    if active_status not in {"pending", "published", "rejected", ""}:
        advanced_filter_count += 1
    return TemplateResponse(
        request,
        "commentail/admin/list.html",
        {
            "comments": page,
            "sites": sites,
            "settings_sites": settings_sites,
            "statuses": Comment.Status.choices,
            "active_status": active_status,
            "advanced_filter_count": advanced_filter_count,
            "status_tabs": status_tabs,
            "page_chooser": page_chooser.render(
                "page",
                selected_page,
                attrs={"id": "commentail-page-filter"},
            ),
            "page_chooser_media": page_chooser.media,
            "mail_allowed": sites.exists(),
            "rules_allowed": sites_for(request.user, "rules").exists(),
            "access_allowed": request.user.is_superuser,
            "bulk_actions": [
                {"value": action, "label": label, "help_text": action_help[action]}
                for action, label in action_labels.items()
                if action in available_actions
            ],
            "return_query": request.GET.urlencode(),
            "previous_query": previous.urlencode(),
            "next_query": following.urlencode(),
        },
    )


def _diff(original: str, proposed: str) -> tuple[SafeString, SafeString]:
    """Escape both texts and mark changed lines without altering stored content."""
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


def _selection_query(request: HttpRequest) -> str:
    """Carry list parameters as query data, never as a redirect destination."""
    parameters = request.POST if request.method == "POST" else request.GET
    return QueryDict(parameters.get("return_query", "")).urlencode()


def _comment_url(identifier: int, query: str) -> str:
    """Link to a card with its tab-local return context, or the direct-entry URL."""
    url = reverse("commentail_admin:detail", args=[identifier])
    return url + ("?" + urlencode({"return_query": query}) if query else "")


def _action_error(
    request: HttpRequest,
    *,
    status: int = 400,
    message: str | None = None,
) -> TemplateResponse:
    """Explain a failed write without exposing item data or replaying the POST."""
    explanations = {
        400: _("The comments or available actions have changed."),
        403: _("Your permissions no longer allow this action."),
        404: _(
            "Some comments are no longer available or you no longer have access to them."
        ),
    }
    query = _selection_query(request)
    list_url = reverse("commentail_admin:list") + (f"?{query}" if query else "")
    has_access = any(
        sites_for(request.user, capability).exists()
        for capability in ("view", "settings", "rules")
    )
    return TemplateResponse(
        request,
        "commentail/admin/action_error.html",
        {
            "explanation": message or explanations[status],
            "back_url": list_url if has_access else reverse("wagtailadmin_home"),
            "has_commentail_access": has_access,
        },
        status=status,
    )


def detail(request: HttpRequest, identifier: int) -> HttpResponse:
    """Show an authorized comment, pending revision, audit trail and failed mail."""
    comment = get_object_or_404(_comments(request), pk=identifier)
    query = _selection_query(request)
    back_url = reverse("commentail_admin:list") + (f"?{query}" if query else "")
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
            "return_query": query,
            "back_url": back_url,
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
    """Check the requested capability before invoking a locked domain transition."""
    action = request.POST.get("action", "")
    capability = _ACTION_CAPABILITIES.get(action)
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


def _delete_confirmation(
    request: HttpRequest,
    identifiers: list[int],
    cancel_url: str,
) -> TemplateResponse:
    """Preview a validated selection without erasing text or recording events."""
    return TemplateResponse(
        request,
        "commentail/admin/confirm_delete.html",
        {
            "identifiers": identifiers,
            "count": len(identifiers),
            "cancel_url": cancel_url,
            "return_query": _selection_query(request),
        },
    )


@require_POST
def action(request: HttpRequest, identifier: int) -> HttpResponse:
    """Apply one moderation action; text erasure requires a confirmation POST."""
    card_url = _comment_url(identifier, _selection_query(request))
    comment = _comments(request).filter(pk=identifier).first()
    if comment is None:
        return _action_error(request, status=404)
    if request.POST.get("action") == "delete":
        if not can(request.user, comment.discussion.site_id, "delete"):
            return _action_error(request, status=403)
        if comment.status not in _BULK_STATUSES["delete"]:
            return _action_error(request)
        if request.POST.get("confirm_delete") != "yes":
            return _delete_confirmation(
                request,
                [comment.pk],
                card_url,
            )
    try:
        _mutate(request, comment)
    except PermissionDenied:
        return _action_error(request, status=403)
    except DomainError as exc:
        return _action_error(
            request, status=403 if str(exc) == _("Permission denied") else 400
        )
    comment.refresh_from_db(fields=["status"])
    messages.success(
        request,
        f"{_('Comment')} #{comment.pk}: {comment.get_status_display()}",
        extra_tags="commentail-action-result",
    )
    return redirect(card_url)


@require_POST
@transaction.atomic
def bulk(request: HttpRequest) -> HttpResponse:
    """Validate every selected comment and apply all transitions atomically.

    Preview erasure without mutation. Execution locks before dependent reads;
    stale state or lost access rolls back the entire selection."""
    identifiers = request.POST.getlist("ids")
    if (
        not identifiers
        or len(identifiers) > 100
        or not all(valid_identifier(value) for value in identifiers)
        or request.POST.get("action") not in _BULK_STATUSES
    ):
        return _action_error(
            request,
            message=_(
                "Select between 1 and 100 comments and choose an available action."
            ),
        )
    identifiers = sorted({int(value) for value in identifiers})
    query = QueryDict(request.POST.get("return_query", "")).urlencode()
    list_url = reverse("commentail_admin:list") + (f"?{query}" if query else "")
    if (
        request.POST["action"] == "delete"
        and request.POST.get("confirm_delete") != "yes"
    ):
        # Check the whole selection before displaying its count. Execution below
        # revalidates access and state inside the existing atomic writer path.
        selected = []
        for identifier in identifiers:
            comment = _comments(request).filter(pk=identifier).first()
            if comment is None:
                return _action_error(request, status=404)
            if not can(request.user, comment.discussion.site_id, "delete"):
                return _action_error(request, status=403)
            if comment.status not in _BULK_STATUSES["delete"]:
                return _action_error(request)
            selected.append(comment.pk)
        return _delete_confirmation(request, selected, list_url)
    try:
        # Acquire the writer lock before dependent reads on SQLite as well.
        Comment.objects.filter(pk__in=identifiers).update(edit_locked=F("edit_locked"))
        for identifier in identifiers:
            comment = get_object_or_404(_comments(request), pk=identifier)
            if comment.status not in _BULK_STATUSES[request.POST["action"]]:
                response = _action_error(request)
                transaction.set_rollback(True)
                return response
            _mutate(request, comment)
    except (DomainError, PermissionDenied, Http404) as exc:
        status = (
            404
            if isinstance(exc, Http404)
            else (
                403
                if isinstance(exc, PermissionDenied)
                or str(exc) == _("Permission denied")
                else 400
            )
        )
        # Build the permission-aware context before queries are blocked by rollback.
        response = _action_error(request, status=status)
        transaction.set_rollback(True)
        return response
    outcome = {
        "approve": _("Approved"),
        "reject": _("Rejected"),
        "hide": _("Hidden"),
        "restore": _("Published"),
        "delete": _("Deleted"),
    }[request.POST["action"]]
    messages.success(
        request,
        f"{outcome}: {len(identifiers)}",
        extra_tags="commentail-action-result",
    )
    return redirect(list_url)


@require_POST
def revision_action(request: HttpRequest, identifier: int) -> HttpResponse:
    """Decide only a pending revision belonging to the authorized comment."""
    revision_id = request.POST.get("revision", "")
    if not valid_identifier(revision_id) or request.POST.get("action") not in {
        "approve",
        "reject",
    }:
        return _action_error(
            request, message=_("Choose an available action for the author revision.")
        )
    card_url = _comment_url(identifier, _selection_query(request))
    comment = _comments(request).filter(pk=identifier).first()
    if comment is None:
        return _action_error(request, status=404)
    if not can(request.user, comment.discussion.site_id, "moderate"):
        return _action_error(request, status=403)
    revision = comment.revisions.filter(pk=revision_id, status="pending").first()
    if revision is None:
        return _action_error(
            request, message=_("This author revision is no longer awaiting moderation.")
        )
    try:
        moderate_revision(
            revision.pk,
            request.POST.get("action"),
            actor=request.user,
            reason=request.POST.get("reason", ""),
        )
    except DomainError as exc:
        return _action_error(
            request, status=403 if str(exc) == _("Permission denied") else 400
        )
    revision.refresh_from_db(fields=["status"])
    messages.success(
        request,
        f"{_('Author revision')}: {revision.get_status_display()}",
        extra_tags="commentail-action-result",
    )
    return redirect(card_url)


@require_POST
def retry_mail(request: HttpRequest, identifier: int) -> HttpResponse:
    """Requeue a permitted failed job and return to its list or recipient card."""
    job = get_object_or_404(
        MailJob.objects.filter(
            recipient__discussion__site__in=sites_for(request.user, "view"),
            comment__discussion__site__in=sites_for(request.user, "view"),
        ),
        pk=identifier,
    )
    card_url = _comment_url(job.recipient_id, _selection_query(request))
    try:
        requeue(job.pk, actor=request.user)
    except DomainError as exc:
        return HttpResponse(str(exc), status=400)
    if request.POST.get("return_to") == "mail":
        return redirect("commentail_admin:mail")
    return redirect(card_url)


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
            if valid_identifier(selected_site)
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


__all__ = [
    "access",
    "action",
    "bulk",
    "detail",
    "index",
    "mail_queue",
    "object_settings",
    "objects_list",
    "retry_mail",
    "revision_action",
    "rule_edit",
    "rules",
    "rules_export",
    "rules_import",
    "settings_view",
]
