"""Server-rendered visitor boundary, owner visibility and signed snapshot windows."""

import re

from django.core import signing
from django.db import transaction
from django.db.models import Exists, F, OuterRef, Prefetch, Q
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils import timezone, translation
from django.utils.html import format_html, format_html_join
from django.utils.safestring import SafeString
from django.utils.translation import gettext as _
from django.views.decorators.csrf import requires_csrf_token
from django.views.decorators.http import require_POST
from wagtail.models import Page, Site

from .admission import accept_request, can_view, issue_form, smtp_configured
from .avatars import author_name, avatar_url, default_avatar
from .detection import DetectionError, has_comments
from .limits import client_ip, consume
from .models import Access, Comment, Discussion, MailJob, Mode
from .objects import discussion_url
from .outbox import resend_confirmation
from .policies import editorial_settings
from .security import create_captcha, remembered_guest
from .services import DomainError, edit_block_reason, revise


@requires_csrf_token
def csrf_failure(request: HttpRequest, reason: str = "") -> HttpResponse:
    """Optional host failure view: recover a draft without accepting its POST.

    Configure CSRF_FAILURE_VIEW explicitly. Only the public submission endpoint
    receives a fresh form; unrelated host views keep Django's default rejection.
    Neither admission nor comment mutations run on this path.
    """
    from django.views.csrf import csrf_failure as default_failure

    match = request.resolver_match
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
    response = TemplateResponse(
        request, "commentail/discussion.html", context, status=403
    )
    response["Cache-Control"] = "private, no-store"
    return response


def get_discussion(
    request: HttpRequest, page_id: int | None = None, discussion_id: int | None = None
) -> Discussion:
    site = Site.find_for_request(request)
    if site is None:
        from django.http import Http404

        raise Http404
    if discussion_id is not None:
        discussion = get_object_or_404(
            Discussion.objects.select_related("site", "content_type"),
            pk=discussion_id,
            site=site,
            page__isnull=True,
        )
        if not can_view(request, discussion):
            from django.http import Http404

            raise Http404
        return discussion
    page = get_object_or_404(Page, pk=page_id).specific
    from django.http import Http404

    try:
        if not has_comments(page, request):
            raise Http404
    except DetectionError:
        raise Http404 from None
    if not can_view(request, Discussion(site=site, page=page)):
        raise Http404
    discussion, _created = Discussion.objects.get_or_create(site=site, page=page)
    return discussion


def render_text(text: str, clickable: bool) -> SafeString:
    if not clickable:
        return format_html("{}", text)
    parts: list[SafeString] = []
    start = 0
    for match in re.finditer(r"https?://[^\s<>]+", text, flags=re.IGNORECASE):
        url = match.group().rstrip(".,;:!?)]}")
        parts.append(format_html("{}", text[start : match.start()]))
        parts.append(
            format_html(
                '<a href="{}" target="_blank" rel="nofollow ugc noopener noreferrer">{}</a>',
                url,
                url,
            )
        )
        start = match.start() + len(url)
    parts.append(format_html("{}", text[start:]))
    return format_html_join("", "{}", ((part,) for part in parts))


def _window(
    request: HttpRequest, discussion: Discussion, key: str, thread: int = 0
) -> tuple[str, int]:
    token = request.GET.get(key)
    if token:
        try:
            payload = signing.loads(token, salt="commentail.window", max_age=86400)
            if (
                payload["discussion"] == discussion.pk
                and payload["thread"] == thread
                and type(payload["limit"]) is int
                and payload["limit"] > 0
            ):
                return payload["snapshot"], payload["limit"]
        except (signing.BadSignature, KeyError, TypeError, ValueError):
            pass
    return timezone.now().isoformat(), 20


def _next(discussion: Discussion, snapshot: str, limit: int, thread: int = 0) -> str:
    return signing.dumps(
        {
            "discussion": discussion.pk,
            "thread": thread,
            "snapshot": snapshot,
            "limit": limit + 20,
        },
        salt="commentail.window",
        compress=True,
    )


def _url(request: HttpRequest, **values: object) -> str:
    params = request.GET.copy()
    for key, value in values.items():
        if value is None:
            params.pop(key, None)
        else:
            params[key] = str(value)
    path = request.path
    if (
        request.method == "POST"
        and request.resolver_match
        and request.resolver_match.url_name in {"submit", "object_submit"}
    ):
        path = discussion_url(get_discussion(request, **request.resolver_match.kwargs))
    return path + "?" + params.urlencode() + "#commentail"


def _present(
    comment: Comment, request: HttpRequest, clickable: bool
) -> dict[str, object]:
    name = author_name(comment, request)
    initials, gradient = default_avatar(name)
    label = (
        _("Comment deleted")
        if comment.status == "deleted"
        else _("Comment hidden")
        if comment.status == "hidden"
        else comment.text
    )
    editable = (
        request.user.is_authenticated
        and comment.user_id == request.user.pk
        and not edit_block_reason(comment)
    )
    return {
        "id": comment.pk,
        "display_name": name,
        "initials": initials,
        "gradient": gradient,
        "avatar_url": avatar_url(comment, request, name),
        "body": render_text(
            label, clickable if comment.status == "published" else False
        ),
        "published_at": comment.published_at,
        "edited_at": comment.edited_at,
        "status": comment.status,
        "status_label": comment.get_status_display(),
        "reason": comment.reason if comment.status == "rejected" else "",
        "resend_url": "",
        "reply_to_id": comment.reply_to_id,
        "reply_to_name": author_name(comment.reply_to, request)
        if comment.reply_to_id
        else "",
        "permalink": discussion_url(comment.discussion)
        + f"?target={comment.pk}#commentail-{comment.pk}",
        "reply_url": _url(request, reply_to=comment.pk, target=comment.pk),
        "edit_url": reverse("commentail:edit", args=[comment.pk]) if editable else "",
    }


def block_context(request: HttpRequest, discussion: Discussion) -> dict[str, object]:
    request.META["COMMENTAIL_PRIVATE"] = True
    options = editorial_settings(discussion)
    base: dict[str, object] = {
        "language_code": translation.get_language(),
        "discussion_id": discussion.pk,
        "page_id": discussion.page_id,
        "options": options,
        "hidden": options.mode == Mode.HIDDEN,
    }
    if options.mode == Mode.HIDDEN:
        return base
    snapshot, limit = _window(request, discussion, "window")
    comments = discussion.comments.select_related(
        "user", "discussion__site", "reply_to__user"
    )
    visible = comments.filter(status="published")
    surviving = Comment.objects.filter(root_id=OuterRef("pk"), status="published")
    roots = (
        comments.filter(root__isnull=True, published_at__lte=snapshot)
        .annotate(surviving=Exists(surviving))
        .filter(
            Q(status="published") | Q(status__in=["hidden", "deleted"], surviving=True)
        )
        .order_by("-published_at", "-pk")
    )
    rows = list(roots[:limit])
    total = roots.count()
    target = None
    if (target_id := request.GET.get("target")) and target_id.isdecimal():
        target = comments.filter(pk=target_id, status="published").first()
        if target:
            root = target.root if target.root_id else target
            if root.pk not in {row.pk for row in rows}:
                rows.append(root)
    presented = []
    for row in rows:
        data = _present(row, request, options.clickable_links)
        replies = visible.filter(root=row, published_at__lte=snapshot).order_by(
            "published_at", "pk"
        )
        count = replies.count()
        data["reply_count"] = count
        opened = request.GET.get("thread") == str(row.pk) or (
            target is not None and target.root_id == row.pk
        )
        _reply_snapshot, reply_limit = _window(request, discussion, "replies", row.pk)
        if opened:
            reply_rows = list(replies[:reply_limit])
            if (
                target is not None
                and target.root_id == row.pk
                and target.pk not in {item.pk for item in reply_rows}
            ):
                reply_rows.append(target)
            data["replies"] = [
                _present(reply, request, options.clickable_links)
                for reply in reply_rows
            ]
        data["expand_url"] = _url(
            request, thread=row.pk, window=_next(discussion, snapshot, limit - 20)
        )
        data["more_replies"] = (
            _url(
                request,
                thread=row.pk,
                replies=_next(discussion, snapshot, reply_limit, row.pk),
                window=_next(discussion, snapshot, limit - 20),
            )
            if opened and count > reply_limit
            else ""
        )
        presented.append(data)
    own = comments.none()
    if request.user.is_authenticated:
        own = comments.filter(user=request.user)
    else:
        identifiers = request.session.get("commentail_own", [])
        own = comments.filter(
            pk__in=identifiers, user__isnull=True, account_deleted=False
        )
    own = (
        own.filter(
            Q(status__in=["awaiting_email", "pending", "rejected"])
            | Q(revisions__status="pending")
        )
        .distinct()
        .prefetch_related("revisions")
        .prefetch_related(
            Prefetch(
                "mail_events",
                queryset=MailJob.objects.filter(kind="confirm").select_related("token"),
                to_attr="confirmation_jobs",
            )
        )
        .order_by("-created_at")[:20]
    )
    private_rows: list[dict[str, object]] = []
    for item in own:
        data = _present(item, request, False)
        if item.status == "awaiting_email":
            jobs = item.confirmation_jobs
            job = jobs[0] if jobs else None
            now = timezone.now()
            expired = job is not None and (
                job.expires_at <= now
                or (job.token_id is not None and job.token.expires_at <= now)
            )
            if expired:
                message = _("The email confirmation deadline has passed.")
            elif job is None or job.status == "cancelled":
                message = _("Confirmation email is unavailable.")
            elif job.status == "sent":
                message = _(
                    "Confirmation email was sent. Check your inbox and spam folder."
                )
            elif job.status == "sending":
                message = _("Confirmation email is being sent.")
            elif job.status == "failed":
                message = _(
                    "There was a problem sending the confirmation email. You can request it again."
                )
            elif job.error:
                message = _(
                    "There was a problem sending the confirmation email. We will retry automatically."
                )
            else:
                message = _("Confirmation email is queued.")
            data["delivery_message"] = message
            data["confirmation_expires_at"] = job.expires_at if job else None
            if (
                job is not None
                and not expired
                and job.status in {"pending", "failed", "sent"}
            ):
                data["resend_url"] = reverse("commentail:resend", args=[item.pk])
        pending = next(
            (
                revision
                for revision in item.revisions.all()
                if revision.status == "pending"
            ),
            None,
        )
        if pending:
            data["body"] = render_text(pending.text, False)
            data["status_label"] = _("Revision awaiting moderation")
        private_rows.append(data)
    can_post = (
        options.mode == Mode.OPEN
        and options.access != Access.NONE
        and (
            (request.user.is_authenticated and options.access != Access.GUESTS)
            or (
                not request.user.is_authenticated
                and options.access != Access.REGISTERED
                and smtp_configured()
            )
        )
    )
    form_key = issue_form(request, discussion) if can_post else ""
    grant = (
        remembered_guest(
            request.COOKIES.get(f"commentail_guest_{discussion.site_id}", ""),
            discussion.site,
        )
        if not request.user.is_authenticated
        else None
    )
    task = None
    if (
        can_post
        and not request.user.is_authenticated
        and (
            grant is None
            or request.POST.get("email", grant.email).casefold()
            != grant.email.casefold()
        )
    ):
        try:
            task = create_captcha(request, discussion.site)
        except DomainError as exc:
            can_post = False
            base["error"] = str(exc)
    reply_to = None
    if identifier := request.POST.get("reply_to", request.GET.get("reply_to", "")):
        reply_to = (
            visible.filter(pk=identifier).first() if identifier.isdecimal() else None
        )
    base.update(
        {
            "rows": presented,
            "own": private_rows,
            "count": visible.count(),
            "more_url": _url(request, window=_next(discussion, snapshot, limit))
            if total > limit
            else "",
            "can_post": can_post,
            "form_key": form_key,
            "captcha": task,
            "remembered_email": grant.email if grant else "",
            "reply_to": _present(reply_to, request, False) if reply_to else None,
            "cancel_reply_url": _url(request, reply_to=None, target=None),
            "submit_url": discussion_url(discussion, submit=True),
        }
    )
    return base


def discussion_view(
    request: HttpRequest, page_id: int | None = None, discussion_id: int | None = None
) -> HttpResponse:
    discussion = get_discussion(request, page_id, discussion_id)
    response = TemplateResponse(
        request, "commentail/discussion.html", block_context(request, discussion)
    )
    response["Cache-Control"] = "private, no-store"
    return response


@require_POST
def submit_view(
    request: HttpRequest, page_id: int | None = None, discussion_id: int | None = None
) -> HttpResponse:
    discussion = get_discussion(request, page_id, discussion_id)
    if request.POST.get("refresh"):
        context = block_context(request, discussion)
        context.update(
            {
                "entered_text": request.POST.get("text", ""),
                "entered_name": request.POST.get("name", ""),
                "entered_email": request.POST.get("email", ""),
            }
        )
        return TemplateResponse(request, "commentail/discussion.html", context)
    try:
        reply = request.POST.get("reply_to", "")
        if reply and not reply.isdecimal():
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
            subscribe=request.POST.get("subscribe") == "on",
        )
    except DomainError as exc:
        context = block_context(request, discussion)
        context.update(
            {
                "error": str(exc),
                "entered_text": request.POST.get("text", ""),
                "entered_name": request.POST.get("name", ""),
                "entered_email": request.POST.get("email", ""),
            }
        )
        return TemplateResponse(
            request, "commentail/discussion.html", context, status=400
        )
    if not request.user.is_authenticated:
        owned = request.session.get("commentail_own", [])
        request.session["commentail_own"] = [*owned[-99:], comment.pk]
    return redirect(
        discussion_url(discussion) + f"?target={comment.pk}#commentail-{comment.pk}"
    )


def edit_view(request: HttpRequest, identifier: int) -> HttpResponse:
    if not request.user.is_authenticated:
        from django.http import Http404

        raise Http404
    comment = get_object_or_404(
        Comment.objects.select_related("discussion__site", "discussion__page"),
        pk=identifier,
        user=request.user,
    )
    discussion = (
        get_discussion(request, comment.discussion.page_id)
        if comment.discussion.page_id
        else get_discussion(request, discussion_id=comment.discussion_id)
    )
    if discussion.pk != comment.discussion_id:
        from django.http import Http404

        raise Http404
    blocked = edit_block_reason(comment)
    error = _(blocked) if blocked else ""
    if request.method == "POST":
        try:
            revise(comment.pk, request.POST.get("text", ""), user=request.user)
            return redirect(
                discussion_url(discussion)
                + f"?target={comment.pk}#commentail-{comment.pk}"
            )
        except DomainError as exc:
            error = str(exc)
    response = TemplateResponse(
        request,
        "commentail/edit.html",
        {
            "text": request.POST.get("text", comment.text),
            "error": error,
            "language_code": translation.get_language(),
            "can_edit": not blocked,
            "return_url": discussion_url(discussion)
            + f"?target={comment.pk}#commentail-{comment.pk}",
        },
        status=400 if request.method == "POST" and error else 200,
    )
    response["Cache-Control"] = "private, no-store"
    return response


@require_POST
@transaction.atomic
def resend_view(request: HttpRequest, identifier: int) -> HttpResponse:
    """Submitting-browser proof permits resending, never renews a capability."""
    from django.http import Http404

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
    return redirect(discussion_url(comment.discussion))
