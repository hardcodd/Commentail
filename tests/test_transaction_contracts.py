"""A failed event enqueue must roll back the entire user-visible transition."""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from wagtail.models import Site

from commentail import outbox
from commentail.models import (
    ActionToken,
    Comment,
    Discussion,
    MailJob,
    ModerationEvent,
    SiteCommentSettings,
)
from commentail.services import (
    confirm_email,
    moderate,
    moderate_revision,
    revise,
    submit,
)


class TransactionContractTests(TestCase):
    def setUp(self):
        site = Site.objects.get(is_default_site=True)
        self.discussion = Discussion.objects.create(site=site, page=site.root_page)
        SiteCommentSettings.objects.create(site=site, notify_publication=True)
        self.author = get_user_model().objects.create_user("transaction-author")
        self.admin = get_user_model().objects.create_superuser(
            "transaction-admin", "", "test"
        )

    def guest(self, text="Guest"):
        return submit(
            self.discussion.pk,
            text=text,
            guest_name="Guest",
            guest_email="guest@example.invalid",
        )

    def fail_after(self, callback):
        def fail(*args, **kwargs):
            before = MailJob.objects.count()
            callback(*args, **kwargs)
            self.assertGreater(MailJob.objects.count(), before)
            raise RuntimeError("Synthetic enqueue failure")

        return fail

    def mail_state(self):
        return MailJob.objects.count(), ActionToken.objects.count()

    def test_failed_reply_enqueue_rolls_back_comment_tokens_and_edit_lock(self):
        root = moderate(
            submit(self.discussion.pk, text="Root", user=self.author).pk,
            "approve",
            actor=self.admin,
        )
        before = self.mail_state()
        with (
            patch(
                "commentail.outbox.accepted",
                side_effect=self.fail_after(outbox.accepted),
            ),
            self.assertRaisesMessage(RuntimeError, "Synthetic enqueue failure"),
        ):
            submit(
                self.discussion.pk,
                text="Uncommitted reply",
                reply_to=root.pk,
                guest_name="Guest",
                guest_email="guest@example.invalid",
            )
        root.refresh_from_db()
        self.assertFalse(root.edit_locked)
        self.assertFalse(root.direct_replies.exists())
        self.assertFalse(Comment.objects.filter(text="Uncommitted reply").exists())
        self.assertEqual(self.mail_state(), before)

    def test_failed_publication_enqueue_rolls_back_status_audit_and_mail(self):
        comment = self.guest()
        confirm_email(comment.pk)
        before = self.mail_state()
        with (
            patch(
                "commentail.outbox.decided", side_effect=self.fail_after(outbox.decided)
            ),
            self.assertRaisesMessage(RuntimeError, "Synthetic enqueue failure"),
        ):
            moderate(comment.pk, "approve", actor=self.admin)
        comment.refresh_from_db()
        self.assertEqual(comment.status, "pending")
        self.assertIsNone(comment.published_at)
        self.assertFalse(ModerationEvent.objects.exists())
        self.assertEqual(self.mail_state(), before)

    def test_failed_revision_enqueue_preserves_original_and_pending_draft(self):
        comment = self.guest("Original")
        confirm_email(comment.pk)
        moderate(comment.pk, "approve", actor=self.admin)
        secret = outbox.token_secret(
            ActionToken.objects.get(comment=comment, purpose="edit")
        )
        revision = revise(
            comment.pk,
            "Private revision",
            edit_token=secret,
            site=self.discussion.site,
        )
        before = self.mail_state()
        events = ModerationEvent.objects.count()
        with (
            patch(
                "commentail.outbox.revision_decided",
                side_effect=self.fail_after(outbox.revision_decided),
            ),
            self.assertRaisesMessage(RuntimeError, "Synthetic enqueue failure"),
        ):
            moderate_revision(revision.pk, "approve", actor=self.admin)
        comment.refresh_from_db()
        revision.refresh_from_db()
        self.assertEqual(comment.text, "Original")
        self.assertIsNone(comment.edited_at)
        self.assertEqual(revision.status, "pending")
        self.assertEqual(revision.text, "Private revision")
        self.assertIsNone(revision.decided_at)
        self.assertEqual(ModerationEvent.objects.count(), events)
        self.assertEqual(self.mail_state(), before)
