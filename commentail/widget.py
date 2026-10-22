"""Assemble the template context after the caller establishes target access.

Reading and private cards share presentation but never visibility queries.
Form and CAPTCHA issuance remains part of rendering, including its ordering.
"""

from collections.abc import Callable
from urllib.parse import urlsplit, urlunsplit

from django.db.models import Count, Exists, OuterRef, Prefetch, Q, QuerySet
from django.http import HttpRequest, QueryDict
from django.urls import reverse
from django.utils import timezone, translation
from django.utils.translation import gettext as _

from .admission import email_configured, issue_form
from .antispam import captcha_required
from .author_access import _edit_owner
from .config import technical_settings
from .drafts import load_draft
from .models import (
    Access,
    Comment,
    CommentRevision,
    Discussion,
    FormTicket,
    MailJob,
    Mode,
)
from .objects import _comment_url, comment_url, discussion_url
from .policies import editorial_settings, email_enabled
from .presentation import _destination, _present, render_text
from .reading import _next, _url, _window
from .security import create_captcha, digest, remembered_guest
from .services import DomainError, edit_block_reason
from .structured import CommentMarkup
from .validation import valid_identifier


def block_context(request: HttpRequest, discussion: Discussion) -> dict[str, object]:
    """Build the stable widget fields for an already authorized discussion.

    Hidden mode returns only base fields. Visible modes may issue form tickets,
    consume a one-shot notice and create a guest CAPTCHA; private rows stay
    separate from public HTML and structured data."""
    request.META["COMMENTAIL_PRIVATE"] = True
    # Fragment responses must keep every reading control on the host document.
    destination, host_available = _destination(discussion)
    request.META["COMMENTAIL_WIDGET_PATH"] = _comment_url(destination)
    options = editorial_settings(discussion)

    def present(
        comment: Comment, clickable: bool, structured_target: str = ""
    ) -> dict[str, object]:
        comment.discussion = discussion
        if comment.reply_to_id and comment.reply_to.discussion_id == discussion.pk:
            comment.reply_to.discussion = discussion
        return _present(
            comment,
            request,
            clickable,
            structured_target,
            destination=destination,
            options=options,
        )

    restored, draft_error = load_draft(request, discussion)
    form_values = request.POST if request.method == "POST" else restored
    edit_identifier = form_values.get("edit_comment") or request.GET.get(
        "edit_comment", ""
    )
    editing = _editing_context(
        request, discussion, form_values, draft_error, edit_identifier
    )
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
        pending_revision=Exists(
            CommentRevision.objects.filter(
                comment_id=OuterRef("pk"),
                status="pending",
            )
        ),
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
    more_roots = roots[limit : limit + 1].exists()
    reply_identifier = (
        request.GET.get("reply_to", form_values.get("reply_to", ""))
        if request.method == "GET"
        else form_values.get("reply_to", request.GET.get("reply_to", ""))
    )
    target = None
    # Validation/refresh POSTs have no navigation query. Keep the addressee's
    # thread visible so progressive clients can restore the inline composer.
    target_id = (
        str(editing["id"]) if editing else request.GET.get("target") or reply_identifier
    )
    if target_id and valid_identifier(target_id):
        target = comments.filter(pk=target_id, status="published").first()
        if target is None:
            private = comments.filter(pk=target_id)
            if request.user.is_authenticated:
                private = private.filter(user=request.user)
            else:
                private = private.filter(
                    pk__in=request.session.get("commentail_own", []),
                    user__isnull=True,
                    account_deleted=False,
                )
            pending = private.first()
            if pending and pending.reply_to_id:
                target = comments.filter(
                    pk=pending.reply_to_id, status="published"
                ).first()
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
    reply_counts = dict(
        visible.filter(
            root_id__in=[row.pk for row in rows],
            published_at__lte=snapshot,
        )
        .values("root_id")
        .annotate(total=Count("pk"))
        .values_list("root_id", "total")
    )
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
        data["reply_window"] = _next(
            discussion, _reply_snapshot, reply_limit - 20, row.pk
        )
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
                item["schema"]
                for item in reply_data
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
    private_rows = _private_rows(request, comments, present)
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
    form_key = ""
    if can_post:
        try:
            form_key = issue_form(
                request,
                discussion,
                previous_key=form_values.get("key", ""),
                previous_id=request.GET.get(
                    "reply_age" if reply_identifier else "form_age", ""
                ),
            )
        except DomainError as exc:
            base["form_error"] = str(exc)
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
    if (
        can_post
        and form_key
        and not request.user.is_authenticated
        and captcha_required(request, discussion.site, email_confirmed)
    ):
        try:
            task = create_captcha(
                request, discussion.site, replace_id=form_values.get("challenge", "")
            )
        except DomainError as exc:
            # Keep the editable draft visible even when issuance is throttled.
            base["captcha_unavailable"] = True
            base["error"] = str(exc)
    reply_to = None
    if identifier := reply_identifier:
        reply_to = (
            visible.filter(pk=identifier).first()
            if valid_identifier(identifier)
            else None
        )
    main_key = ""
    if form_key and reply_to is not None:
        try:
            main_key = issue_form(
                request, discussion, previous_id=request.GET.get("form_age", "")
            )
        except DomainError as exc:
            base["form_error"] = str(exc)
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
            "main_form_key": main_key,
            "form_age": FormTicket.objects.get(digest=digest(form_key)).pk
            if form_key
            else "",
            "main_form_age": FormTicket.objects.get(digest=digest(main_key)).pk
            if main_key
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


def _private_comments(
    request: HttpRequest,
    comments: QuerySet[Comment],
) -> QuerySet[Comment]:
    """Select at most 20 owner-visible statuses with bounded revision/mail reads."""
    if request.user.is_authenticated:
        own = comments.filter(user=request.user)
    else:
        identifiers = request.session.get("commentail_own", [])
        own = comments.filter(
            pk__in=identifiers, user__isnull=True, account_deleted=False
        )
    return (
        own.filter(
            Q(status__in=["awaiting_email", "pending", "rejected"])
            | Q(revisions__status="pending")
        )
        .distinct()
        .prefetch_related(
            Prefetch(
                "revisions",
                queryset=CommentRevision.objects.filter(status="pending"),
            )
        )
        .prefetch_related(
            Prefetch(
                "mail_events",
                queryset=MailJob.objects.filter(kind="confirm").select_related("token"),
                to_attr="confirmation_jobs",
            )
        )
        .order_by("-created_at")[:20]
    )


def _confirmation_delivery(item: Comment) -> dict[str, object]:
    """Describe a prefetched confirmation job without disclosing backend errors."""
    result: dict[str, object] = {}
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
        message = _("Confirmation email was sent. Check your inbox and spam folder.")
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
    result["delivery_message"] = message
    result["confirmation_expires_at"] = job.expires_at if job else None
    if job is not None and not expired and job.status in {"pending", "failed", "sent"}:
        result["resend_url"] = reverse("commentail:resend", args=[item.pk])
    return result


def _private_rows(
    request: HttpRequest,
    comments: QuerySet[Comment],
    present: Callable[[Comment, bool], dict[str, object]],
) -> list[dict[str, object]]:
    """Present owner-only statuses and pending revision text outside public rows."""
    own = _private_comments(request, comments)
    private_rows: list[dict[str, object]] = []
    for item in own:
        data = present(item, False)
        if item.status == "awaiting_email":
            data.update(_confirmation_delivery(item))
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
    return private_rows


def _editing_context(
    request: HttpRequest,
    discussion: Discussion,
    form_values: QueryDict,
    draft_error: str,
    edit_identifier: str,
) -> dict[str, object] | None:
    """Restore an inline editor only after exact author ownership is verified."""
    editing = None
    if valid_identifier(edit_identifier):
        candidate = (
            discussion.comments.select_related("discussion__site")
            .filter(pk=edit_identifier)
            .first()
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
    return editing
