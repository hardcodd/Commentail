"""Persisted discussion states; mutations go through transactional services."""

import uuid
from typing import ClassVar

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from wagtail.contrib.settings.models import BaseSiteSetting


class Policy(models.TextChoices):
    ALL = "all", _("Review all")
    GUESTS = "guests", _("Review guests")
    NONE = "none", _("Publish immediately")
    RULES = "rules", _("Apply rules")


class Mode(models.TextChoices):
    OPEN = "open", _("Open")
    READ_ONLY = "read_only", _("Read only")
    HIDDEN = "hidden", _("Hidden")


class Access(models.TextChoices):
    ALL = "all", _("Guests and registered users")
    REGISTERED = "registered", _("Registered users")
    GUESTS = "guests", _("Guests")
    NONE = "none", _("Nobody")


class SiteCommentSettings(BaseSiteSetting):
    email_enabled = models.BooleanField(default=True)
    mode = models.CharField(max_length=16, choices=Mode.choices, default=Mode.OPEN)
    moderation = models.CharField(
        max_length=16, choices=Policy.choices, default=Policy.ALL
    )
    access = models.CharField(max_length=16, choices=Access.choices, default=Access.ALL)
    max_length = models.PositiveIntegerField(default=5000)
    clickable_links = models.BooleanField(default=False)
    notify_publication = models.BooleanField(default=False)
    notify_rejection = models.BooleanField(default=False)


class Discussion(models.Model):
    site = models.ForeignKey("wagtailcore.Site", on_delete=models.CASCADE)
    page = models.ForeignKey(
        "wagtailcore.Page", null=True, blank=True, on_delete=models.CASCADE
    )
    content_type = models.ForeignKey(
        "contenttypes.ContentType", null=True, blank=True, on_delete=models.CASCADE
    )
    object_id = models.CharField(max_length=255, blank=True, default="")
    mode = models.CharField(max_length=16, choices=Mode.choices, blank=True, default="")
    moderation = models.CharField(
        max_length=16, choices=Policy.choices, blank=True, default=""
    )
    access = models.CharField(
        max_length=16, choices=Access.choices, blank=True, default=""
    )
    max_length = models.PositiveIntegerField(null=True, blank=True)
    clickable_links = models.BooleanField(null=True, blank=True)
    notify_publication = models.BooleanField(null=True, blank=True)
    notify_rejection = models.BooleanField(null=True, blank=True)
    version = models.PositiveBigIntegerField(default=0)

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["site", "page"], name="commentail_site_page_unique"
            ),
            models.UniqueConstraint(
                fields=["site", "content_type", "object_id"],
                name="commentail_site_object_unique",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        page__isnull=False, content_type__isnull=True, object_id=""
                    )
                    | (
                        models.Q(page__isnull=True, content_type__isnull=False)
                        & ~models.Q(object_id="")
                    )
                ),
                name="commentail_one_target",
            ),
        ]

    @property
    def target_label(self) -> str:
        if self.page_id:
            return self.page.title
        return f"{self.content_type.app_label}.{self.content_type.model} / {self.object_id}"


class Comment(models.Model):
    class Status(models.TextChoices):
        AWAITING_EMAIL = "awaiting_email", _("Awaiting email")
        PENDING = "pending", _("Awaiting moderation")
        PUBLISHED = "published", _("Published")
        REJECTED = "rejected", _("Rejected")
        HIDDEN = "hidden", _("Hidden")
        DELETED = "deleted", _("Deleted")

    discussion = models.ForeignKey(
        Discussion, on_delete=models.CASCADE, related_name="comments"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    account_deleted = models.BooleanField(default=False)
    # New names allow 40 graphemes; preserve longer historical names.
    guest_name = models.TextField(blank=True)
    email = models.EmailField(blank=True)
    email_confirmed_at = models.DateTimeField(null=True, blank=True)
    text = models.TextField()
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.AWAITING_EMAIL
    )
    root = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="thread_replies",
    )
    reply_to = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="direct_replies",
    )
    edit_locked = models.BooleanField(default=False)
    suspicious = models.BooleanField(default=False)
    language = models.CharField(max_length=20, default="en")
    reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    published_at = models.DateTimeField(null=True, blank=True)
    edited_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["discussion", "status", "published_at", "id"]),
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["status", "published_at", "id"], name="commentail_publication_order"),
            models.Index(fields=["root", "status", "published_at", "id"], name="commentail_reply_order"),
            models.Index(
                fields=["discussion", "published_at", "id"],
                condition=models.Q(root__isnull=True), name="commentail_root_order",
            ),
        ]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=(
                    models.Q(root__isnull=True, reply_to__isnull=True)
                    | models.Q(root__isnull=False, reply_to__isnull=False)
                ),
                name="commentail_reply_pair",
            )
        ]

    @property
    def display_name(self) -> str:
        if self.account_deleted:
            return str(_("Deleted user"))
        if self.user_id:
            getter = getattr(self.user, "get_full_name", None)
            name = str(getter() or "").strip() if callable(getter) else ""
            username = self.user.get_username()
            return name or (username if "@" not in username else str(_("User")))
        return self.guest_name


class CommentRevision(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", _("Awaiting moderation")
        APPROVED = "approved", _("Approved")
        REJECTED = "rejected", _("Rejected")

    comment = models.ForeignKey(
        Comment, on_delete=models.CASCADE, related_name="revisions"
    )
    text = models.TextField()
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.PENDING
    )
    reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["comment"],
                condition=models.Q(status="pending"),
                name="commentail_one_pending_revision",
            )
        ]


class ModerationRule(models.Model):
    class Action(models.TextChoices):
        REVIEW = "review", _("Review")
        REJECT = "reject", _("Reject")

    phrase = models.CharField(max_length=255)
    action = models.CharField(max_length=10, choices=Action.choices)
    enabled = models.BooleanField(default=True)


class SiteGroupPermission(models.Model):
    group = models.ForeignKey("auth.Group", on_delete=models.CASCADE)
    site = models.ForeignKey("wagtailcore.Site", on_delete=models.CASCADE)
    moderate = models.BooleanField(default=False)
    view = models.BooleanField(default=False)
    hide = models.BooleanField(default=False)
    delete = models.BooleanField(default=False)
    settings = models.BooleanField(default=False)
    rules = models.BooleanField(default=False)

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["group", "site"], name="commentail_group_site_unique"
            )
        ]


class ModerationEvent(models.Model):
    comment = models.ForeignKey(
        Comment, on_delete=models.CASCADE, related_name="events"
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL
    )
    action = models.CharField(max_length=32)
    created_at = models.DateTimeField(auto_now_add=True)


class ActionToken(models.Model):
    nonce = models.UUIDField(default=uuid.uuid4, editable=False)
    digest = models.CharField(max_length=64, unique=True)
    comment = models.ForeignKey(Comment, on_delete=models.CASCADE)
    purpose = models.CharField(
        max_length=16,
        choices=[
            ("confirm", "Confirm"),
            ("edit", "Edit"),
            ("view", "View"),
            ("unsubscribe", "Unsubscribe"),
        ],
    )
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)


class GuestGrant(models.Model):
    digest = models.CharField(max_length=64, unique=True)
    site = models.ForeignKey("wagtailcore.Site", on_delete=models.CASCADE)
    email = models.EmailField()
    confirmed_at = models.DateTimeField()
    expires_at = models.DateTimeField(db_index=True)


class CaptchaChallenge(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    site = models.ForeignKey("wagtailcore.Site", on_delete=models.CASCADE)
    session_digest = models.CharField(max_length=64)
    answer = models.IntegerField()
    backend = models.CharField(max_length=255, blank=True)
    provider_id = models.CharField(max_length=255, blank=True)
    expires_at = models.DateTimeField(db_index=True)
    attempts = models.PositiveIntegerField(default=0)
    used = models.BooleanField(default=False)

    class Meta:
        indexes: ClassVar[list[models.Index]] = [
            models.Index(
                fields=["site", "session_digest"], condition=models.Q(used=False),
                name="commentail_active_captcha",
            ),
        ]


class SubmissionRecord(models.Model):
    discussion = models.ForeignKey(Discussion, on_delete=models.CASCADE)
    actor_digest = models.CharField(max_length=64)
    key_digest = models.CharField(max_length=64)
    payload_digest = models.CharField(max_length=64)
    comment = models.OneToOneField(Comment, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["discussion", "actor_digest", "key_digest"],
                name="commentail_submission_unique",
            )
        ]


class RateEvent(models.Model):
    site = models.ForeignKey("wagtailcore.Site", on_delete=models.CASCADE)
    kind = models.CharField(max_length=16)
    subject_digest = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["site", "kind", "subject_digest", "created_at"])
        ]


class ReplySubscription(models.Model):
    comment = models.OneToOneField(Comment, on_delete=models.CASCADE)
    enabled = models.BooleanField(default=True)


class MailJob(models.Model):
    revision = models.ForeignKey(
        CommentRevision, null=True, blank=True, on_delete=models.CASCADE
    )
    event_key = models.CharField(max_length=160, unique=True)
    kind = models.CharField(max_length=16)
    comment = models.ForeignKey(
        Comment, on_delete=models.CASCADE, related_name="mail_events"
    )
    recipient = models.ForeignKey(
        Comment, on_delete=models.CASCADE, related_name="recipient_jobs"
    )
    token = models.ForeignKey(
        ActionToken, null=True, blank=True, on_delete=models.CASCADE
    )
    language = models.CharField(max_length=20, default="en")
    status = models.CharField(max_length=16, default="pending", db_index=True)
    attempts = models.PositiveIntegerField(default=0)
    next_attempt_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()
    lease_until = models.DateTimeField(null=True, blank=True)
    claim = models.UUIDField(null=True, blank=True)
    error = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["status", "next_attempt_at"])
        ]


class FormTicket(models.Model):
    digest = models.CharField(max_length=64, unique=True)
    discussion = models.ForeignKey(Discussion, on_delete=models.CASCADE)
    session_digest = models.CharField(max_length=64)
    expires_at = models.DateTimeField(db_index=True)
    draft = models.JSONField(default=dict, blank=True)
