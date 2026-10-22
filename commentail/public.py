"""Public HTTP authorization, submissions, editing and browser draft recovery."""

from django.db import transaction
from django.db.models import F
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.utils.translation import gettext as _
from django.views.decorators.csrf import requires_csrf_token
from django.views.decorators.http import require_http_methods, require_POST
from wagtail.models import Page, Site

from .admission import accept_request, can_view
from .author_access import _edit_owner, guest_edit_secret
from .detection import DetectionError, has_comments
from .drafts import clear_drafts, is_document, save_draft
from .limits import client_ip, consume
from .models import (
    Comment,
    Discussion,
    ReplySubscription,
)
from .objects import (
    comment_url,
    discussion_url,
)
from .outbox import resend_confirmation
from .presentation import render_text
from .reading import _next, _url, _window
from .services import DomainError, revise
from .validation import valid_identifier
from .widget import block_context


def _draft_redirect(
    request: HttpRequest, discussion: Discussion, error: str = ""
) -> HttpResponse | None:
    """Preserve a document POST as a private draft and redirect with HTTP 303."""
    if not is_document(request):
        return None

    destination = save_draft(request, discussion, error)
    if destination is None:
        raise Http404

    response = redirect(destination)
    response.status_code = 303
    response["Cache-Control"] = "private, no-store"
    return response


@requires_csrf_token
def csrf_failure(request: HttpRequest, reason: str = "") -> HttpResponse:
    """Optional host failure view: recover a draft without accepting its POST.

    Configure CSRF_FAILURE_VIEW explicitly. Public submission and editing
    receive fresh forms; unrelated host views keep Django's default rejection.
    Neither admission nor comment mutations run on this path.
    """
    from django.views.csrf import csrf_failure as default_failure

    match = request.resolver_match
    if match and match.func is edit_view:
        comment = _edit_target(request, match.kwargs["identifier"])
        return _edit_failure(
            request,
            comment,
            _(
                "The form could not be verified. Your draft is preserved; review it and send again."
            ),
            status=403,
        )
    if match is None or match.func is not submit_view:
        return default_failure(request, reason=reason)
    discussion = get_discussion(request, **match.kwargs)
    context = block_context(request, discussion)
    context.update(
        {
            "error": _(
                "The form could not be verified. Your draft is preserved; review it and send again."
            ),
            "entered_text": request.POST.get("text", ""),
            "entered_name": request.POST.get("name", ""),
            "entered_email": request.POST.get("email", ""),
        }
    )
    if (
        response := _draft_redirect(request, discussion, str(context["error"]))
    ) is not None:
        return response
    response = TemplateResponse(request, "commentail/block.html", context, status=403)
    response["Cache-Control"] = "private, no-store"
    return response


def get_discussion(
    request: HttpRequest, page_id: int | None = None, discussion_id: int | None = None
) -> Discussion:
    """Resolve a Site-scoped target after access and widget checks, or raise 404.

    Page discussions are created lazily; object discussions must already exist."""
    site = Site.find_for_request(request)
    if site is None:
        raise Http404

    if discussion_id is not None:
        discussion = get_object_or_404(
            Discussion.objects.select_related("site", "content_type"),
            pk=discussion_id,
            site=site,
            page__isnull=True,
        )
        if not can_view(request, discussion):
            raise Http404
        return discussion

    page = get_object_or_404(Page, pk=page_id).specific
    try:
        if not has_comments(page, request):
            raise Http404
    except DetectionError:
        raise Http404 from None
    if not can_view(request, Discussion(site=site, page=page)):
        raise Http404
    discussion, _created = Discussion.objects.get_or_create(site=site, page=page)
    return discussion


def discussion_view(
    request: HttpRequest, page_id: int | None = None, discussion_id: int | None = None
) -> HttpResponse:
    """Return a private fragment, or redirect document navigation to its host."""
    discussion = get_discussion(request, page_id, discussion_id)
    # Browser document navigation belongs on the host. Fetch's default */*
    # still receives the server-rendered fragment used by progressive controls.
    if is_document(request):
        destination = comment_url(discussion, navigation=request.GET)
        if destination.split("?", 1)[0].split("#", 1)[0] == discussion_url(discussion):
            raise Http404
        response = redirect(destination)
        response["Cache-Control"] = "private, no-store"
        response["Vary"] = "Accept, Sec-Fetch-Dest"
        return response
    response = TemplateResponse(
        request, "commentail/block.html", block_context(request, discussion)
    )
    response["Cache-Control"] = "private, no-store"
    return response


@require_POST
def submit_view(
    request: HttpRequest, page_id: int | None = None, discussion_id: int | None = None
) -> HttpResponse:
    """Refresh a form or admit one submission, retaining drafts on domain errors."""
    discussion = get_discussion(request, page_id, discussion_id)
    if request.POST.get("refresh"):
        if (response := _draft_redirect(request, discussion)) is not None:
            return response
        context = block_context(request, discussion)
        context.update(
            {
                "entered_text": request.POST.get("text", ""),
                "entered_name": request.POST.get("name", ""),
                "entered_email": request.POST.get("email", ""),
            }
        )
        return TemplateResponse(request, "commentail/block.html", context)
    try:
        reply = request.POST.get("reply_to", "")
        if reply and not valid_identifier(reply):
            raise DomainError("Invalid reply target")
        comment = accept_request(
            request,
            discussion.pk,
            request.POST.get("key", ""),
            text=request.POST.get("text", ""),
            guest_name=request.POST.get("name", ""),
            guest_email=request.POST.get("email", ""),
            reply_to=int(reply) if reply else None,
            challenge_id=request.POST.get("challenge", ""),
            answer=request.POST.get("answer", ""),
        )
    except DomainError as exc:
        if (response := _draft_redirect(request, discussion, str(exc))) is not None:
            return response
        context = block_context(request, discussion)
        context.update(
            {
                "error": str(exc),
                "entered_text": request.POST.get("text", ""),
                "entered_name": request.POST.get("name", ""),
                "entered_email": request.POST.get("email", ""),
            }
        )
        return TemplateResponse(request, "commentail/block.html", context, status=400)
    if not request.user.is_authenticated:
        owned = request.session.get("commentail_own", [])
        request.session["commentail_own"] = [*owned[-99:], comment.pk]
    if ReplySubscription.objects.filter(comment=comment, enabled=True).exists():
        request.session["commentail_mail_notice"] = discussion.pk
    clear_drafts(request, discussion)
    return redirect(comment_url(discussion, comment.pk, navigation=request.GET))


def _edit_target(request: HttpRequest, identifier: int) -> Comment:
    """Resolve the target again and require exact author ownership before editing."""
    comment = get_object_or_404(
        Comment.objects.select_related("discussion__site", "discussion__page"),
        pk=identifier,
    )
    discussion = (
        get_discussion(request, comment.discussion.page_id)
        if comment.discussion.page_id
        else get_discussion(request, discussion_id=comment.discussion_id)
    )
    if discussion.pk != comment.discussion_id or not _edit_owner(request, comment):
        raise Http404
    return comment


def _edit_failure(
    request: HttpRequest, comment: Comment, error: str, *, status: int = 400
) -> HttpResponse:
    """Recover only the authorized target's draft, never a posted identifier."""
    values = request.POST.copy()
    values["edit_comment"] = str(comment.pk)
    request.POST = values
    if (response := _draft_redirect(request, comment.discussion, error)) is not None:
        return response
    context = block_context(request, comment.discussion)
    if context["editing"]:
        context["editing"]["error"] = error
    response = TemplateResponse(
        request, "commentail/block.html", context, status=status
    )
    response["Cache-Control"] = "private, no-store"
    return response


@require_http_methods(["GET", "POST"])
def edit_view(request: HttpRequest, identifier: int) -> HttpResponse:
    """Legacy GET locates the inline form; POST saves an authorized revision."""
    comment = _edit_target(request, identifier)
    discussion = comment.discussion
    if request.method == "GET":
        response = redirect(
            comment_url(
                discussion, comment.pk, navigation={"edit_comment": str(comment.pk)}
            )
        )
        response.status_code = 303
    else:
        try:
            if comment.user_id is not None:
                revise(comment.pk, request.POST.get("text", ""), user=request.user)
            else:
                revise(
                    comment.pk,
                    request.POST.get("text", ""),
                    edit_token=guest_edit_secret(request, comment),
                    site=discussion.site,
                )
        except DomainError as exc:
            return _edit_failure(request, comment, str(exc))
        else:
            clear_drafts(request, discussion)
            navigation = request.GET.copy()
            navigation.pop("edit_comment", None)
            response = redirect(
                comment_url(discussion, comment.pk, navigation=navigation)
            )
            if comment.user_id is None:
                response.status_code = 303
    response["Cache-Control"] = "private, no-store"
    return response


@require_POST
@transaction.atomic
def resend_view(request: HttpRequest, identifier: int) -> HttpResponse:
    """Submitting-browser proof permits resending, never renews a capability."""
    site = Site.find_for_request(request)
    if site is None or request.user.is_authenticated:
        raise Http404
    Site.objects.filter(pk=site.pk).update(port=F("port"))
    comment = get_object_or_404(
        Comment.objects.select_related("discussion__site", "discussion__page"),
        pk=identifier,
        pk__in=request.session.get("commentail_own", []),
        discussion__site=site,
        user__isnull=True,
        account_deleted=False,
    )
    if not can_view(request, comment.discussion):
        raise Http404
    try:
        consume(site, "resend", comment.email.casefold(), client_ip(request, site))
        resend_confirmation(comment.pk)
    except DomainError as exc:
        transaction.set_rollback(True)
        return HttpResponse(str(exc), status=400)
    return redirect(comment_url(comment.discussion, comment.pk))


__all__ = [
    "_next",
    "_url",
    "_window",
    "block_context",
    "csrf_failure",
    "discussion_view",
    "edit_view",
    "get_discussion",
    "guest_edit_secret",
    "render_text",
    "resend_view",
    "submit_view",
]
