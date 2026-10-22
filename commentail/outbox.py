"""Transactional notification producers and bounded, leased background delivery.

No user text is copied into jobs. Delivery runs outside the database transaction.
A timed-out transport may have delivered a message: retries are intentionally
at least once, with a stable Message-ID, not an exactly-once delivery promise.
"""

import uuid
from datetime import datetime, timedelta
from smtplib import SMTPException, SMTPRecipientsRefused, SMTPResponseException
from typing import TypedDict
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser
from django.core.mail import EmailMultiAlternatives, get_connection
from django.core.mail.backends.smtp import EmailBackend
from django.db import transaction
from django.db.models import F, Q
from django.template import TemplateDoesNotExist, TemplateSyntaxError
from django.template.loader import get_template, render_to_string
from django.urls import NoReverseMatch, reverse
from django.utils import timezone, translation
from wagtail.models import Site

from .config import technical_settings
from .mail_access import GuestRecipient, _can_receive, _email
from .models import ActionToken, Comment, CommentRevision, MailJob, ReplySubscription
from .policies import editorial_settings, email_enabled
from .security import digest, issue_token, token_secret
from .services import DomainError, _permission


class MailBackendError(Exception):
    """Keep arbitrary backend failures within the queue's bounded retry policy.

    Only transport construction/sending is wrapped. Rendering and domain failures
    retain their own handling; backend diagnostics must never reach saved status.
    """

    def __init__(self, error: Exception) -> None:
        super().__init__(type(error).__name__)
        self.error = error


def _enqueue(
    comment: Comment,
    kind: str,
    key: str,
    recipient: Comment | None = None,
    purpose: str | None = None,
    revision: CommentRevision | None = None,
) -> MailJob | None:
    """Called in the same transaction as the state transition."""
    if not email_enabled(comment.discussion.site_id):
        return None
    recipient = recipient or comment
    config = technical_settings(comment.discussion.site)
    expires = timezone.now() + timedelta(seconds=config["MAIL_RETENTION_SECONDS"])
    token = None
    if purpose:
        if purpose == "confirm":
            expires = min(
                expires,
                comment.created_at + timedelta(seconds=config["EMAIL_CONFIRM_SECONDS"]),
            )
        elif purpose == "edit":
            expires = min(
                expires,
                comment.published_at + timedelta(seconds=config["EDIT_WINDOW_SECONDS"]),
            )
        token_expiry = (
            expires
            if purpose != "unsubscribe"
            else timezone.now() + timedelta(seconds=config["ACTION_LINK_SECONDS"])
        )
        # Repetition must not create another token/job or renew its expiry.
        existing = MailJob.objects.filter(event_key=key).first()
        if existing:
            return existing
        secret = issue_token(recipient, purpose, token_expiry)
        token = ActionToken.objects.get(digest=digest(secret))
    job, _created = MailJob.objects.get_or_create(
        event_key=key,
        defaults={
            "kind": kind,
            "revision": revision,
            "comment": comment,
            "recipient": recipient,
            "token": token,
            "language": recipient.language,
            "expires_at": expires,
        },
    )
    return job


def accepted(comment: Comment) -> None:
    """Queue guest proof or final-state notices inside the submission transaction."""
    if comment.status == "awaiting_email":
        if not ActionToken.objects.filter(comment=comment, purpose="view").exists():
            issue_token(
                comment,
                "view",
                timezone.now()
                + timedelta(
                    seconds=technical_settings(comment.discussion.site)[
                        "ACTION_LINK_SECONDS"
                    ]
                ),
            )
        _enqueue(comment, "confirm", f"confirm:{comment.pk}", purpose="confirm")
    elif comment.status in {"published", "rejected"}:
        decided(comment)


def decided(comment: Comment, *, after_moderation: bool = False) -> None:
    """Queue publication notices only for approval after a pending state.

    Immediate publication still sends guest edit links and subscribed replies.
    Rejection notifications continue to follow their separate setting.
    """
    options = editorial_settings(comment.discussion)
    if comment.status == "published":
        if comment.user_id is None and not comment.account_deleted:
            _enqueue(comment, "edit", f"edit:{comment.pk}", purpose="edit")
        if after_moderation and options.notify_publication:
            _enqueue(comment, "published", f"published:{comment.pk}")
        if (
            comment.reply_to_id
            and ReplySubscription.objects.filter(
                comment_id=comment.reply_to_id, enabled=True
            ).exists()
        ):
            _enqueue(
                comment,
                "reply",
                f"reply:{comment.pk}",
                recipient=comment.reply_to,
                purpose="unsubscribe",
            )
    elif comment.status == "rejected" and options.notify_rejection:
        _enqueue(comment, "rejected", f"rejected:{comment.pk}")


def revision_decided(
    revision: CommentRevision, *, after_moderation: bool = False
) -> None:
    """Skip publication mail for instant edits; retain configured rejection notices."""
    options = editorial_settings(revision.comment.discussion)
    kind = "published" if revision.status == "approved" else "rejected"
    if (kind == "published" and after_moderation and options.notify_publication) or (
        kind == "rejected" and options.notify_rejection
    ):
        _enqueue(
            revision.comment, kind, f"revision:{revision.pk}:{kind}", revision=revision
        )


def _valid(job: MailJob) -> bool:
    """Revalidate recipient access, original deadlines and current delivery state."""
    now = timezone.now()
    if (
        not email_enabled(job.comment.discussion.site_id)
        or job.expires_at <= now
        or not _email(job.recipient)
        or not _can_receive(job.recipient)
    ):
        return False
    if job.token and (
        job.token.expires_at <= now
        or digest(token_secret(job.token)) != job.token.digest
    ):
        return False
    if job.comment.status == "deleted":
        return False
    if job.kind == "confirm" and job.comment.status != "awaiting_email":
        return False
    if job.kind == "edit" and (
        job.comment.status != "published" or job.comment.edit_locked
    ):
        return False
    if job.kind == "reply":
        return (
            job.comment.status == "published"
            and job.recipient.status == "published"
            and ReplySubscription.objects.filter(
                comment=job.recipient, enabled=True
            ).exists()
        )
    return True


class MailTemplateError(ValueError):
    """A non-retryable subject/template contract failure."""


class MailTemplateContext(TypedDict):
    """Stable mail context; deliberately excludes internal models and body text."""

    kind: str
    author_name: str
    site_name: str
    site_url: str
    target_url: str
    action_url: str
    view_url: str
    reason: str
    is_revision: bool
    expires_at: datetime


def deliver(job: MailJob) -> None:
    """Render notification metadata only; comment/revision bodies never enter mail."""
    site = job.comment.discussion.site
    target_url, action_url, view_url = _mail_urls(job)
    reason = ""
    if job.kind == "rejected":
        reason = job.revision.reason if job.revision_id else job.comment.reason
    # Generated author labels must use the recipient locale, just like templates.
    with translation.override(job.language):
        # No models/request/context processors: overrides cannot traverse to user text.
        context: MailTemplateContext = {
            "kind": job.kind,
            "author_name": job.comment.display_name,
            "site_name": site.site_name or site.hostname,
            "site_url": site.root_url,
            "target_url": target_url,
            "action_url": action_url,
            "view_url": view_url,
            "reason": reason,
            "is_revision": job.revision_id is not None,
            "expires_at": job.expires_at,
        }
        message = _render_message(job, context)
        _send_message(message, site)


@transaction.atomic
def claim_job(identifier: int) -> MailJob | None:
    """Only one worker can claim a due row; delivery is outside this lock."""
    now = timezone.now()
    claim = uuid.uuid4()
    query = MailJob.objects.filter(pk=identifier, next_attempt_at__lte=now).filter(
        Q(status="pending") | Q(status="sending", lease_until__lte=now)
    )
    if not query.update(
        status="sending",
        claim=claim,
        attempts=F("attempts") + 1,
        lease_until=now + timedelta(minutes=5),
    ):
        return None
    job = MailJob.objects.select_related(
        "comment__user",
        "revision",
        "comment__discussion__site",
        "comment__discussion__page",
        "recipient__discussion__page",
        "recipient__discussion__site",
        "recipient__user",
        "token",
    ).get(pk=identifier)
    seconds = technical_settings(job.comment.discussion.site)["MAIL_LEASE_SECONDS"]
    MailJob.objects.filter(pk=identifier, claim=claim).update(
        lease_until=now + timedelta(seconds=seconds)
    )
    return job


def _permanent(exc: Exception) -> bool:
    if isinstance(exc, SMTPResponseException):
        return exc.smtp_code >= 500
    if isinstance(exc, SMTPRecipientsRefused):
        return all(code >= 500 for code, _message in exc.recipients.values())
    return False


def process_mail(limit: int = 100) -> int:
    """Process due jobs, cancelling lost access and delaying hidden discussions."""
    now = timezone.now()
    MailJob.objects.filter(status="pending", expires_at__lte=now).update(
        status="cancelled"
    )
    identifiers = list(
        MailJob.objects.filter(next_attempt_at__lte=now)
        .filter(Q(status="pending") | Q(status="sending", lease_until__lte=now))
        .order_by("next_attempt_at", "pk")
        .values_list("pk", flat=True)[:limit]
    )
    sent = 0
    for identifier in identifiers:
        job = claim_job(identifier)
        if job is None:
            continue
        owner = MailJob.objects.filter(pk=job.pk, claim=job.claim, status="sending")
        try:
            valid = _valid(job)
        except DomainError:
            owner.update(
                status="failed",
                error="Guest mail access handler failed",
                lease_until=None,
            )
            continue
        if not valid:
            owner.update(status="cancelled", lease_until=None)
            continue
        if editorial_settings(job.comment.discussion).mode == "hidden":
            owner.update(
                status="pending",
                attempts=F("attempts") - 1,
                next_attempt_at=timezone.now() + timedelta(minutes=1),
                lease_until=None,
            )
            continue
        intervals = technical_settings(job.comment.discussion.site)[
            "MAIL_RETRY_SECONDS"
        ]
        if job.attempts > len(intervals) + 1:
            owner.update(
                status="failed",
                error="Delivery attempt budget exhausted",
                lease_until=None,
            )
            continue
        try:
            deliver(job)
        except (
            TemplateDoesNotExist,
            TemplateSyntaxError,
            NoReverseMatch,
            MailTemplateError,
            DomainError,
        ) as exc:
            owner.update(status="failed", error=type(exc).__name__, lease_until=None)
        except (MailBackendError, SMTPException, OSError, ValueError) as exc:
            failure = exc.error if isinstance(exc, MailBackendError) else exc
            error = type(
                failure
            ).__name__  # Never store a transport dump or secret URL.
            if _permanent(failure) or job.attempts > len(intervals):
                owner.update(status="failed", error=error, lease_until=None)
            else:
                owner.update(
                    status="pending",
                    error=error,
                    lease_until=None,
                    next_attempt_at=timezone.now()
                    + timedelta(seconds=intervals[job.attempts - 1]),
                )
        else:
            owner.update(status="sent", error="", lease_until=None)
            sent += 1
    return sent


@transaction.atomic
def requeue(job_id: int, *, actor: AbstractBaseUser) -> None:
    # Lock before reading and permission checking; a failure rolls back the write.
    """Reset a failed job only after a locked permission and eligibility recheck.

    Retain its original capability and expiry; rejection rolls back the lock."""
    if not MailJob.objects.filter(pk=job_id).update(attempts=F("attempts")):
        raise DomainError("Mail job does not exist")
    job = MailJob.objects.select_related(
        "comment__discussion__site",
        "recipient__discussion__site",
        "recipient__discussion__page",
        "recipient__user",
        "token",
    ).get(pk=job_id)
    _permission(actor, job.comment.discussion, "moderate")
    if job.status != "failed" or not _valid(job):
        raise DomainError("This message cannot be resent")
    job.status = "pending"
    job.next_attempt_at = timezone.now()
    job.attempts = 0
    job.error = ""
    job.save()


@transaction.atomic
def resend_confirmation(comment_id: int) -> None:
    """Trusted owner boundary reuses the original job, token and deadline.

    The HTTP caller must prove guest ownership and consume site-wide quotas.
    A currently claimed job cannot be reset while delivery is in flight.
    """
    query = MailJob.objects.filter(comment_id=comment_id, kind="confirm")
    if not query.update(attempts=F("attempts")):
        raise DomainError("This message cannot be resent")
    job = query.select_related(
        "comment__discussion__site",
        "recipient__discussion__site",
        "recipient__discussion__page",
        "recipient__user",
        "token",
    ).get()
    if job.status == "sending" or not _valid(job):
        raise DomainError("This message cannot be resent")
    job.status = "pending"
    job.next_attempt_at = timezone.now()
    job.attempts = 0
    job.error = ""
    job.save(update_fields=["status", "next_attempt_at", "attempts", "error"])


def _mail_urls(job: MailJob) -> tuple[str, str, str]:
    """Resolve the host and purpose links before applying the recipient locale."""
    site = job.comment.discussion.site
    from .objects import ObjectAccessError, target_url

    try:
        page_url = target_url(job.comment.discussion)
    except ObjectAccessError as exc:
        raise DomainError("Object URL handler failed") from exc
    if page_url.startswith("/"):
        page_url = site.root_url + page_url
    parts = urlsplit(page_url)
    query = dict(parse_qsl(parts.query))
    query["target"] = str(job.comment_id)
    target_url = urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            parts.path,
            urlencode(query),
            f"commentail-{job.comment_id}",
        )
    )
    action_url = ""
    if job.token:
        action_url = site.root_url + reverse(
            "commentail:action",
            args=[job.token.purpose],
            query={"token": token_secret(job.token)},
        )
    view_url = ""
    if job.kind == "confirm":
        view_token = ActionToken.objects.filter(
            comment=job.comment, purpose="view", expires_at__gt=timezone.now()
        ).first()
        if view_token:
            view_url = site.root_url + reverse(
                "commentail:action",
                args=["view"],
                query={"token": token_secret(view_token)},
            )
    return target_url, action_url, view_url


def _render_message(
    job: MailJob, context: MailTemplateContext
) -> EmailMultiAlternatives:
    """Build multipart metadata mail; a missing HTML entry point opts into text only.

    Missing includes in an existing HTML override remain errors, as do empty or
    multiline subjects. Render without request/model-bearing context processors.
    """
    site = job.comment.discussion.site
    prefix = f"commentail/emails/{job.kind}"
    subject = render_to_string(prefix + "_subject.txt", context).strip()
    if not subject or "\n" in subject or "\r" in subject:
        raise MailTemplateError("Invalid email subject")
    message = EmailMultiAlternatives(
        subject,
        render_to_string(prefix + ".txt", context),
        settings.DEFAULT_FROM_EMAIL,
        [_email(job.recipient)],
        headers={"Message-ID": f"<commentail-{job.pk}@{site.hostname}>"},
    )
    html_name = prefix + ".html"
    try:
        html_template = get_template(html_name)
    except TemplateDoesNotExist as exc:
        if not exc.args or exc.args[0] != html_name:
            raise
    else:
        # Missing includes in an existing override are errors, not opt-outs.
        message.attach_alternative(html_template.render(context), "text/html")
    return message


def _send_message(message: EmailMultiAlternatives, site: Site) -> None:
    """Bound SMTP timeout and isolate arbitrary backend exceptions for retries."""
    try:
        connection = get_connection()
        if isinstance(connection, EmailBackend):
            ceiling = max(
                1, min(30, technical_settings(site)["MAIL_LEASE_SECONDS"] // 2)
            )
            connection.timeout = (
                ceiling
                if connection.timeout is None
                else min(ceiling, connection.timeout)
            )
        message.connection = connection
        if message.send() != 1:
            raise OSError("Backend did not report successful delivery")
    except Exception as exc:
        # Django backends may raise provider-specific exceptions. Only this
        # transport boundary retries them; do not hide template/domain bugs.
        raise MailBackendError(exc) from exc


__all__ = [
    "GuestRecipient",
    "MailBackendError",
    "MailTemplateContext",
    "MailTemplateError",
    "_can_receive",
    "accepted",
    "claim_job",
    "decided",
    "deliver",
    "process_mail",
    "requeue",
    "resend_confirmation",
    "revision_decided",
]
