"""Server-rendered visitor boundary, owner visibility and signed snapshot windows."""

import re
from urllib.parse import urlsplit, urlunsplit

from django.core import signing
from django.db import transaction
from django.db.models import Count, Exists, F, OuterRef, Prefetch, Q
from django.http import Http404, HttpRequest, HttpResponse, QueryDict
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils import timezone, translation
from django.utils.html import format_html, format_html_join
from django.utils.safestring import SafeString
from django.utils.translation import gettext as _
from django.views.decorators.csrf import requires_csrf_token
from django.views.decorators.http import require_http_methods, require_POST
from wagtail.models import Page, Site

from .admission import accept_request, can_view, email_configured, issue_form
from .avatars import author_name, avatar_url, default_avatar
from .config import technical_settings
from .detection import DetectionError, has_comments
from .drafts import clear_drafts, is_document, load_draft, save_draft
from .limits import client_ip, consume
from .models import (
    Access,
    Comment,
    CommentRevision,
    Discussion,
    MailJob,
    Mode,
    ReplySubscription,
)
from .objects import (
    ObjectAccessError,
    _comment_url,
    comment_url,
    discussion_url,
    target_url,
)
from .outbox import resend_confirmation
from .policies import EditorialSettings, editorial_settings, email_enabled
from .security import create_captcha, remembered_guest, verify_token
from .services import DomainError, edit_block_reason, revise
from .structured import CommentMarkup, comment_markup
from .validation import valid_identifier


def _draft_redirect(
    request: HttpRequest, discussion: Discussion, error: str = ""
) -> HttpResponse | None:
    if not is_document(request):
        return None
    destination = save_draft(request, discussion, error)
    if destination is None:
        from django.http import Http404

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
        return _edit_failure(request, comment, _(
            "The form could not be verified. Your draft is preserved; review it and send again."
        ), status=403)
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
    if (response := _draft_redirect(request, discussion, str(context["error"]))) is not None:
        return response
    response = TemplateResponse(
        request, "commentail/block.html", context, status=403
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
    for token in request.GET.getlist(key):
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
    destination = urlsplit(request.META.get("COMMENTAIL_WIDGET_PATH", request.path))
    params = QueryDict(destination.query, mutable=True)
    for key in request.GET:
        params.setlist(key, request.GET.getlist(key))
    for key, value in values.items():
        if value is None:
            params.pop(key, None)
        else:
            params[key] = str(value)
    return urlunsplit((
        destination.scheme, destination.netloc, destination.path,
        params.urlencode(), "commentail",
    ))


def guest_edit_secret(request: HttpRequest, comment: Comment) -> str | None:
    """A remembered email is insufficient; revalidate this exact edit capability."""
    secret = request.session.get("commentail_edits", {}).get(str(comment.pk))
    if not secret or comment.user_id is not None or comment.account_deleted:
        return None
    try:
        token = verify_token(secret, "edit", comment.discussion.site)
    except DomainError:
        return None
    return secret if token.comment_id == comment.pk else None


def _edit_owner(request: HttpRequest, comment: Comment) -> bool:
    return bool(
        (
            request.user.is_authenticated
            and request.user.is_active
            and comment.user_id == request.user.pk
        )
        or guest_edit_secret(request, comment)
    )


def _present(
    comment: Comment, request: HttpRequest, clickable: bool, structured_target: str = "",
    *, destination: str | None = None, options: EditorialSettings | None = None,
) -> dict[str, object]:
    name = author_name(comment, request)
    initials, gradient = default_avatar(name)
    options = options if options is not None else editorial_settings(comment.discussion)
    user = comment.user
    staff = bool(
        options.highlight_staff and not comment.account_deleted and user
        and user.is_active
        and (getattr(user, "is_staff", False) or getattr(user, "is_superuser", False))
    )
    if comment.status == "deleted":
        label = _("Comment deleted")
    elif comment.status == "hidden":
        label = _("Comment hidden")
    else:
        label = comment.text
    editable = _edit_owner(request, comment) and not edit_block_reason(
        comment, options=options, pending_revision=getattr(comment, "pending_revision", None),
    )
    destination = destination if destination is not None else _destination(comment.discussion)[0]
    permalink = _comment_url(destination, comment.pk)
    return {
        "id": comment.pk,
        "display_name": name,
        "highlight_staff": staff,
        "show_crown": staff and bool(getattr(user, "is_superuser", False)),
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
        "permalink": permalink,
        "schema": comment_markup(
            comment, name, structured_target, request.build_absolute_uri(permalink),
        ) if structured_target else None,
        "reply_url": _url(request, reply_to=comment.pk, target=comment.pk),
        "edit_url": _comment_url(
            destination, comment.pk,
            navigation={"edit_comment": str(comment.pk)},
        ) if editable else "",
    }


def _destination(discussion: Discussion) -> tuple[str, bool]:
    """Resolve the host once per render; retain service recovery on URL failure."""
    try:
        return target_url(discussion), True
    except ObjectAccessError:
        return discussion_url(discussion), False


def block_context(request: HttpRequest, discussion: Discussion) -> dict[str, object]:
    request.META["COMMENTAIL_PRIVATE"] = True
    # Fragment responses must keep every reading control on the host document.
    destination, host_available = _destination(discussion)
    request.META["COMMENTAIL_WIDGET_PATH"] = _comment_url(destination)
    options = editorial_settings(discussion)

    def present(comment: Comment, clickable: bool, structured_target: str = "") -> dict[str, object]:
        comment.discussion = discussion
        if comment.reply_to_id and comment.reply_to.discussion_id == discussion.pk:
            comment.reply_to.discussion = discussion
        return _present(
            comment, request, clickable, structured_target,
            destination=destination, options=options,
        )
    restored, draft_error = load_draft(request, discussion)
    form_values = request.POST if request.method == "POST" else restored
    edit_identifier = form_values.get("edit_comment") or request.GET.get("edit_comment", "")
    editing = None
    if valid_identifier(edit_identifier):
        candidate = (
            discussion.comments.select_related("discussion__site")
            .filter(pk=edit_identifier).first()
        )
        if candidate is not None and _edit_owner(request, candidate):
            blocked = edit_block_reason(candidate)
            editing = {
                "id": candidate.pk,
                "text": form_values.get("text", candidate.text),
                "error": draft_error or (_(blocked) if blocked else ""),
                "can_edit": not blocked,
                "url": reverse("commentail:edit", args=[candidate.pk]),
                "cancel_url": comment_url(discussion, candidate.pk),
            }
    base: dict[str, object] = {
        "language_code": translation.get_language(),
        "discussion_id": discussion.pk,
        "page_id": discussion.page_id,
        "options": options,
        "hidden": options.mode == Mode.HIDDEN,
        "entered_text": "" if edit_identifier else form_values.get("text", ""),
        "entered_name": form_values.get("name", ""),
        "entered_email": form_values.get("email", ""),
        "error": "" if edit_identifier else draft_error,
        "editing": editing,
    }
    if options.mode == Mode.HIDDEN:
        return base
    notice = request.session.get("commentail_mail_notice")
    if notice == discussion.pk:
        request.session.pop("commentail_mail_notice")
        base["mail_notice"] = _("We’ll email you about replies.")
    snapshot, limit = _window(request, discussion, "window")
    comments = discussion.comments.select_related("user", "reply_to__user").annotate(
        pending_revision=Exists(CommentRevision.objects.filter(
            comment_id=OuterRef("pk"), status="pending",
        )),
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
    more_roots = roots[limit:limit + 1].exists()
    reply_identifier = (
        request.GET.get("reply_to", form_values.get("reply_to", ""))
        if request.method == "GET"
        else form_values.get("reply_to", request.GET.get("reply_to", ""))
    )
    target = None
    # Validation/refresh POSTs have no navigation query. Keep the addressee's
    # thread visible so progressive clients can restore the inline composer.
    target_id = str(editing["id"]) if editing else request.GET.get("target") or reply_identifier
    if target_id and valid_identifier(target_id):
        target = comments.filter(pk=target_id, status="published").first()
        if target is None:
            private = comments.filter(pk=target_id)
            if request.user.is_authenticated:
                private = private.filter(user=request.user)
            else:
                private = private.filter(
                    pk__in=request.session.get("commentail_own", []),
                    user__isnull=True, account_deleted=False,
                )
            pending = private.first()
            if pending and pending.reply_to_id:
                target = comments.filter(pk=pending.reply_to_id, status="published").first()
        if target:
            root = target.root if target.root_id else target
            if root.pk not in {row.pk for row in rows}:
                if target.root_id and rows and root.published_at < rows[0].published_at:
                    rows.append(root)
                else:
                    rows.insert(0, root)
    structured_mode = technical_settings(discussion.site)["STRUCTURED_DATA"]
    structured_target = ""
    if structured_mode != "off" and host_available:
        absolute = urlsplit(request.build_absolute_uri(destination))
        structured_target = urlunsplit(absolute._replace(fragment=""))
    reply_counts = dict(visible.filter(
        root_id__in=[row.pk for row in rows], published_at__lte=snapshot,
    ).values("root_id").annotate(total=Count("pk")).values_list("root_id", "total"))
    structured_comments: list[CommentMarkup] = []
    presented = []
    for row in rows:
        data = present(row, options.clickable_links, structured_target)
        if isinstance(data["schema"], CommentMarkup):
            structured_comments.append(data["schema"])
        replies = visible.filter(root=row, published_at__lte=snapshot).order_by(
            "published_at", "pk"
        )
        count = reply_counts.get(row.pk, 0)
        data["reply_count"] = count
        opened = str(row.pk) in request.GET.getlist("thread") or (
            target is not None and target.root_id == row.pk
        )
        _reply_snapshot, reply_limit = _window(request, discussion, "replies", row.pk)
        data["opened"] = opened
        data["reply_window"] = _next(discussion, _reply_snapshot, reply_limit - 20, row.pk)
        if opened:
            reply_rows = list(replies[:reply_limit])
            if (
                target is not None
                and target.root_id == row.pk
                and target.pk not in {item.pk for item in reply_rows}
            ):
                reply_rows.append(target)
            # The addressed reply may be newer than the stable pagination
            # snapshot. Its thread still needs to render when that count is zero.
            data["reply_count"] = max(count, len(reply_rows))
            reply_data = [
                present(reply, options.clickable_links, structured_target)
                for reply in reply_rows
            ]
            data["replies"] = reply_data
            structured_comments.extend(
                item["schema"] for item in reply_data
                if isinstance(item["schema"], CommentMarkup)
            )
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
    base["structured_microdata"] = structured_mode in ("both", "microdata")
    base["structured_comments"] = (
        structured_comments if structured_mode in ("both", "json_ld") else []
    )
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
        .prefetch_related(Prefetch(
            "revisions", queryset=CommentRevision.objects.filter(status="pending"),
        ))
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
        data = present(item, False)
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
                and email_enabled(discussion.site_id)
                and email_configured()
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
    email_confirmed = grant is not None and (
        form_values.get("email", grant.email).strip().casefold()
        == grant.email.casefold()
    )
    task = None
    if can_post and not request.user.is_authenticated and not email_confirmed:
        try:
            task = create_captcha(request, discussion.site)
        except DomainError as exc:
            can_post = False
            base["error"] = str(exc)
    reply_to = None
    if identifier := reply_identifier:
        reply_to = (
            visible.filter(pk=identifier).first() if valid_identifier(identifier) else None
        )
    base.update(
        {
            "window_token": _next(discussion, snapshot, limit - 20),
            "rows": presented,
            "own": private_rows,
            "count": visible.count(),
            "more_url": _url(request, window=_next(discussion, snapshot, limit))
            if more_roots
            else "",
            "can_post": can_post,
            "form_key": form_key,
            "main_form_key": issue_form(request, discussion)
            if can_post and reply_to is not None
            else "",
            "captcha": task,
            "remembered_email": grant.email if grant else "",
            "guest_email_confirmed": email_confirmed,
            "reply_to": present(reply_to, False) if reply_to else None,
            "cancel_reply_url": _url(request, reply_to="", target=None),
            "submit_url": discussion_url(discussion, submit=True),
        }
    )
    return base


def discussion_view(
    request: HttpRequest, page_id: int | None = None, discussion_id: int | None = None
) -> HttpResponse:
    discussion = get_discussion(request, page_id, discussion_id)
    # Browser document navigation belongs on the host. Fetch's default */*
    # still receives the server-rendered fragment used by progressive controls.
    if is_document(request):
        destination = comment_url(discussion, navigation=request.GET)
        if destination.split("?", 1)[0].split("#", 1)[0] == discussion_url(discussion):
            from django.http import Http404

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
        return TemplateResponse(
            request, "commentail/block.html", context, status=400
        )
    if not request.user.is_authenticated:
        owned = request.session.get("commentail_own", [])
        request.session["commentail_own"] = [*owned[-99:], comment.pk]
    if ReplySubscription.objects.filter(comment=comment, enabled=True).exists():
        request.session["commentail_mail_notice"] = discussion.pk
    clear_drafts(request, discussion)
    return redirect(comment_url(discussion, comment.pk, navigation=request.GET))


def _edit_target(request: HttpRequest, identifier: int) -> Comment:
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
    response = TemplateResponse(request, "commentail/block.html", context, status=status)
    response["Cache-Control"] = "private, no-store"
    return response


@require_http_methods(["GET", "POST"])
def edit_view(request: HttpRequest, identifier: int) -> HttpResponse:
    """Legacy GET locates the inline form; POST saves an authorized revision."""
    comment = _edit_target(request, identifier)
    discussion = comment.discussion
    if request.method == "GET":
        response = redirect(comment_url(
            discussion, comment.pk, navigation={"edit_comment": str(comment.pk)}
        ))
        response.status_code = 303
    else:
        try:
            if comment.user_id is not None:
                revise(comment.pk, request.POST.get("text", ""), user=request.user)
            else:
                revise(
                    comment.pk, request.POST.get("text", ""),
                    edit_token=guest_edit_secret(request, comment), site=discussion.site,
                )
        except DomainError as exc:
            return _edit_failure(request, comment, str(exc))
        else:
            clear_drafts(request, discussion)
            navigation = request.GET.copy()
            navigation.pop("edit_comment", None)
            response = redirect(comment_url(discussion, comment.pk, navigation=navigation))
            if comment.user_id is None:
                response.status_code = 303
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
    return redirect(comment_url(comment.discussion, comment.pk))
