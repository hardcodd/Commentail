"""Trusted domain operations, not HTTP authorization endpoints.

Callers must establish page access, guest proof, CAPTCHA and rate limits before
entry. Email confirmation accepts an ID only after a purpose token is verified
by the delivery layer. A discussion write serializes all dependent transitions
on both SQLite and PostgreSQL; no reliance on SQLite select_for_update.
"""

from datetime import timedelta
from typing import Literal

from django.contrib.auth.models import AbstractBaseUser
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from wagtail.models import Site

from .config import technical_settings
from .models import (
    Access,
    Comment,
    CommentRevision,
    Discussion,
    Mode,
    ModerationEvent,
    SiteGroupPermission,
)
from .policies import EditorialSettings, editorial_settings, policy_result
from .text import character_count


class DomainError(ValueError):
    """A forbidden or invalid transition; the transaction has no side effects."""

    def __init__(self, message: str) -> None:
        from django.utils.translation import gettext

        super().__init__(gettext(message))


def _discussion(identifier: int) -> Discussion:
    # This write is deliberately first: SQLite acquires its writer reservation
    # before dependent state is read. PostgreSQL locks the same discussion row.
    if not Discussion.objects.filter(pk=identifier).update(version=F("version") + 1):
        raise DomainError("Discussion does not exist")
    return Discussion.objects.select_related("site", "page").get(pk=identifier)


def _comment(identifier: int) -> tuple[Comment, Discussion]:
    # Use a subquery in the first write, not a separate SELECT before locking.
    if not Discussion.objects.filter(comments__pk=identifier).update(
        version=F("version") + 1
    ):
        raise DomainError("Comment does not exist")
    comment = Comment.objects.filter(pk=identifier).first()
    if comment is None:
        raise DomainError("Comment does not exist")
    return comment, Discussion.objects.select_related("site", "page").get(
        pk=comment.discussion_id
    )


def _text(text: str, options: EditorialSettings) -> None:
    if (
        not isinstance(text, str)
        or not text.strip()
        or character_count(text) > options.max_length
    ):
        raise DomainError("Comment is empty or too long")


def _permission(
    actor: AbstractBaseUser,
    discussion: Discussion,
    action: Literal["moderate", "delete", "hide"],
) -> None:
    if not actor.is_active or not actor.is_authenticated:
        raise DomainError("Permission denied")
    if actor.is_superuser:
        return
    if not SiteGroupPermission.objects.filter(
        group__user=actor, site_id=discussion.site_id, **{action: True}
    ).exists():
        raise DomainError("Permission denied")


def _event(comment: Comment, actor: AbstractBaseUser, action: str) -> None:
    ModerationEvent.objects.create(comment=comment, actor=actor, action=action)


def _publish(comment: Comment) -> None:
    comment.status = Comment.Status.PUBLISHED
    if comment.published_at is None:
        comment.published_at = timezone.now()


@transaction.atomic
def submit(
    discussion_id: int,
    *,
    text: str,
    user: AbstractBaseUser | None = None,
    guest_name: str = "",
    guest_email: str = "",
    reply_to: int | None = None,
    suspicious: bool = False,
    language: str = "en",
    subscribe: bool = False,
) -> Comment:
    """Accept one message after the delivery layer's access/anti-spam checks."""
    discussion = _discussion(discussion_id)
    options = editorial_settings(discussion)
    _text(text, options)
    if options.mode != Mode.OPEN:
        raise DomainError("Discussion is closed")
    guest = user is None
    if user is not None and (not user.is_active or not user.is_authenticated):
        raise DomainError("Account cannot comment")
    if (
        options.access == Access.NONE
        or (guest and options.access == Access.REGISTERED)
        or (not guest and options.access == Access.GUESTS)
    ):
        raise DomainError("Author cannot comment")
    if guest:
        guest_name = guest_name.strip()
        if not guest_name or character_count(guest_name) > 40:
            raise DomainError(
                "Guest name is required and must be at most 40 characters"
            )
        try:
            validate_email(guest_email)
        except ValidationError as exc:
            raise DomainError("Guest email is required") from exc
    target = None
    if reply_to is not None:
        target = Comment.objects.filter(
            pk=reply_to, discussion=discussion, status=Comment.Status.PUBLISHED
        ).first()
        if target is None:
            raise DomainError(
                "Only a visible published comment in this discussion accepts replies"
            )
        Comment.objects.filter(pk=target.pk).update(edit_locked=True)
    comment = Comment(
        discussion=discussion,
        user=user,
        text=text,
        guest_name=guest_name if guest else "",
        email=guest_email.strip() if guest else str(getattr(user, "email", "") or ""),
        reply_to=target,
        root=(target.root or target) if target else None,
        suspicious=suspicious,
        language=language,
    )
    if guest:
        comment.status = Comment.Status.AWAITING_EMAIL
    else:
        comment.status = policy_result(
            text, options.moderation, guest=False, suspicious=suspicious
        )
        if comment.status == Comment.Status.PUBLISHED:
            _publish(comment)
    comment.save()
    from .models import ReplySubscription
    from .outbox import accepted

    if subscribe:
        ReplySubscription.objects.create(comment=comment)
    accepted(comment)
    return comment


@transaction.atomic
def confirm_email(comment_id: int) -> Comment:
    """Confirm after external proof verification; expired comments remain for cleanup."""
    comment, discussion = _comment(comment_id)
    if comment.status != Comment.Status.AWAITING_EMAIL:
        return comment
    if timezone.now() >= comment.created_at + timedelta(
        seconds=technical_settings(discussion.site)["EMAIL_CONFIRM_SECONDS"]
    ):
        raise DomainError("Confirmation expired")
    comment.email_confirmed_at = timezone.now()
    # A changed closed mode prevents submissions, not processing prior messages.
    comment.status = policy_result(
        comment.text,
        editorial_settings(discussion).moderation,
        guest=True,
        suspicious=comment.suspicious,
    )
    if comment.status == Comment.Status.PUBLISHED:
        _publish(comment)
    comment.save()
    from .outbox import decided

    decided(comment)
    return comment


def edit_block_reason(comment: Comment) -> str:
    """Read-only eligibility shared by forms and the locked author-write service."""
    discussion = comment.discussion
    options = editorial_settings(discussion)
    if (
        options.mode != Mode.OPEN
        or comment.status != Comment.Status.PUBLISHED
        or comment.edit_locked
    ):
        return "Comment cannot be edited"
    if (
        comment.published_at is None
        or timezone.now()
        >= comment.published_at
        + timedelta(seconds=technical_settings(discussion.site)["EDIT_WINDOW_SECONDS"])
    ):
        return "Editing window expired"
    if comment.revisions.filter(status=CommentRevision.Status.PENDING).exists():
        return "A revision already awaits moderation"
    return ""


@transaction.atomic
def revise(
    comment_id: int,
    text: str,
    *,
    user: AbstractBaseUser | None = None,
    edit_token: str | None = None,
    site: Site | None = None,
) -> CommentRevision:
    """Author revision; guest capability is separate from account ownership."""
    comment, discussion = _comment(comment_id)
    options = editorial_settings(discussion)
    _text(text, options)
    if user is None:
        from .security import verify_token

        if (
            not edit_token
            or site is None
            or site.pk != discussion.site_id
            or comment.user_id is not None
            or comment.account_deleted
        ):
            raise DomainError("Guest editing requires an edit link")
        token = verify_token(edit_token, "edit", site)
        if token.comment_id != comment.pk:
            raise DomainError("This link cannot edit that comment")
    elif not user.is_active or not user.is_authenticated or comment.user_id != user.pk:
        raise DomainError("Only the author can edit")
    if reason := edit_block_reason(comment):
        raise DomainError(reason)
    result = policy_result(
        text, options.moderation, guest=user is None, suspicious=comment.suspicious
    )
    revision = CommentRevision.objects.create(
        comment=comment,
        text=text if result == "pending" else "",
        status="approved" if result == "published" else result,
        decided_at=None if result == "pending" else timezone.now(),
    )
    if result == "published":
        comment.text = text
        comment.edited_at = timezone.now()
        comment.save()
    if result != "pending":
        from .outbox import revision_decided

        revision_decided(revision)
    return revision


@transaction.atomic
def moderate(
    comment_id: int,
    action: Literal["approve", "reject"],
    *,
    actor: AbstractBaseUser,
    reason: str = "",
) -> Comment:
    comment, discussion = _comment(comment_id)
    _permission(actor, discussion, "moderate")
    if action not in {"approve", "reject"}:
        raise DomainError("Unknown moderation action")
    desired = (
        Comment.Status.PUBLISHED if action == "approve" else Comment.Status.REJECTED
    )
    if comment.status == desired:
        return comment
    if comment.status != Comment.Status.PENDING:
        raise DomainError("Only pending comments can be decided")
    if action == "approve":
        _publish(comment)
    else:
        comment.status = desired
        comment.reason = reason
    comment.save()
    _event(comment, actor, action)
    from .outbox import decided

    decided(comment)
    return comment


@transaction.atomic
def moderate_revision(
    revision_id: int,
    action: Literal["approve", "reject"],
    *,
    actor: AbstractBaseUser,
    reason: str = "",
) -> CommentRevision:
    if not Discussion.objects.filter(comments__revisions__pk=revision_id).update(
        version=F("version") + 1
    ):
        raise DomainError("Revision does not exist")
    revision = CommentRevision.objects.select_related("comment__discussion__site").get(
        pk=revision_id
    )
    comment, discussion = revision.comment, revision.comment.discussion
    _permission(actor, discussion, "moderate")
    if action not in {"approve", "reject"}:
        raise DomainError("Unknown revision action")
    desired = "approved" if action == "approve" else "rejected"
    if revision.status == desired:
        return revision
    if revision.status != "pending" or comment.status not in {"published", "hidden"}:
        raise DomainError("Revision cannot be decided")
    if action == "approve":
        comment.text = revision.text
        comment.edited_at = timezone.now()
        comment.save()
    revision.text = ""
    revision.status = desired
    revision.reason = reason if action == "reject" else ""
    revision.decided_at = timezone.now()
    revision.save()
    _event(comment, actor, "revision_" + action)
    from .outbox import revision_decided

    revision_decided(revision)
    return revision


@transaction.atomic
def remove(comment_id: int, *, actor: AbstractBaseUser) -> Comment:
    comment, discussion = _comment(comment_id)
    _permission(actor, discussion, "delete")
    if comment.status != Comment.Status.DELETED:
        comment.text = ""
        comment.reason = ""
        comment.status = Comment.Status.DELETED
        comment.revisions.all().delete()
        comment.save()
        _event(comment, actor, "delete")
    return comment


@transaction.atomic
def hide(comment_id: int, *, actor: AbstractBaseUser) -> Comment:
    comment, discussion = _comment(comment_id)
    _permission(actor, discussion, "hide")
    if comment.status == Comment.Status.HIDDEN:
        return comment
    if comment.status != Comment.Status.PUBLISHED:
        raise DomainError("Only published comments can be hidden")
    comment.status = Comment.Status.HIDDEN
    comment.save()
    _event(comment, actor, "hide")
    return comment


@transaction.atomic
def restore(comment_id: int, *, actor: AbstractBaseUser) -> Comment:
    comment, discussion = _comment(comment_id)
    _permission(actor, discussion, "hide")
    if comment.status == Comment.Status.PUBLISHED:
        return comment
    if comment.status != Comment.Status.HIDDEN:
        raise DomainError("Only hidden comments can be restored")
    comment.status = Comment.Status.PUBLISHED
    comment.save()
    _event(comment, actor, "restore")
    return comment


def cleanup_unconfirmed() -> int:
    """Erase expired unverified messages, rechecking under the discussion lock."""
    count = 0
    for identifier in (
        Comment.objects.filter(status=Comment.Status.AWAITING_EMAIL)
        .values_list("pk", flat=True)
        .iterator()
    ):
        with transaction.atomic():
            try:
                comment, discussion = _comment(identifier)
            except DomainError:
                continue
            deadline = comment.created_at + timedelta(
                seconds=technical_settings(discussion.site)["EMAIL_CONFIRM_SECONDS"]
            )
            if (
                comment.status == Comment.Status.AWAITING_EMAIL
                and timezone.now() >= deadline
            ):
                comment.delete()
                count += 1
    return count


@transaction.atomic
def submit_once(
    discussion_id: int,
    key: str,
    *,
    text: str,
    user: AbstractBaseUser | None = None,
    guest_name: str = "",
    guest_email: str = "",
    reply_to: int | None = None,
    suspicious: bool = False,
    language: str = "en",
    subscribe: bool = False,
) -> Comment:
    """Return an identical prior submission; access must be checked on each call.

    Keys come from a server-issued, bounded-life form in the delivery adapter.
    The same key and actor cannot submit a changed payload. Hashes contain no
    retrievable text or guest email; the record dies with its comment.
    """
    import hashlib
    import json

    from .models import SubmissionRecord

    discussion = _discussion(discussion_id)
    if not key or len(key) > 256:
        raise DomainError("Invalid submission key")
    actor = (
        "user:" + str(user.pk)
        if user is not None
        else "guest:" + guest_email.strip().casefold()
    )

    def sha(value: str) -> str:
        return hashlib.sha256(value.encode()).hexdigest()

    payload = sha(
        json.dumps(
            [text, guest_name, guest_email, reply_to, language, subscribe],
            ensure_ascii=False,
        )
    )
    record = (
        SubmissionRecord.objects.filter(
            discussion=discussion, actor_digest=sha(actor), key_digest=sha(key)
        )
        .select_related("comment")
        .first()
    )
    if record:
        if record.payload_digest != payload:
            raise DomainError("Submission key was already used with different content")
        return record.comment
    comment = submit(
        discussion_id,
        text=text,
        user=user,
        guest_name=guest_name,
        guest_email=guest_email,
        reply_to=reply_to,
        suspicious=suspicious,
        language=language,
        subscribe=subscribe,
    )
    SubmissionRecord.objects.create(
        discussion=discussion,
        actor_digest=sha(actor),
        key_digest=sha(key),
        payload_digest=payload,
        comment=comment,
    )
    return comment
