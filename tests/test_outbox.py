from datetime import timedelta
from smtplib import (
    SMTPAuthenticationError,
    SMTPDataError,
    SMTPRecipientsRefused,
    SMTPServerDisconnected,
)
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase
from django.utils import timezone
from wagtail.models import Site

from commentail.models import (
    Discussion,
    MailJob,
    ReplySubscription,
    SiteCommentSettings,
)
from commentail.outbox import claim_job, deliver, process_mail, requeue
from commentail.security import confirm_from_token, unsubscribe
from commentail.services import (
    DomainError,
    confirm_email,
    moderate,
    moderate_revision,
    revise,
    submit,
)


class OutboxTests(TestCase):
    def setUp(self):
        self.site = Site.objects.get(is_default_site=True)
        self.discussion = Discussion.objects.create(
            site=self.site, page=self.site.root_page
        )
        self.admin = get_user_model().objects.create_superuser(
            "admin", "admin@example.invalid", "synthetic"
        )
        self.author = get_user_model().objects.create_user(
            "writer", email="writer@example.invalid"
        )
        self.options = SiteCommentSettings.objects.create(site=self.site)

    def guest(self):
        return submit(
            self.discussion.pk,
            text="Guest",
            guest_name="Guest",
            guest_email="guest@example.invalid",
        )

    def test_confirmation_job_and_get_style_verification(self):
        from commentail.security import token_secret, verify_token

        comment = self.guest()
        job = MailJob.objects.get(kind="confirm")
        secret = token_secret(job.token)
        verify_token(secret, "confirm", self.site)
        comment.refresh_from_db()
        self.assertEqual(comment.status, "awaiting_email")
        confirm_from_token(secret, self.site)
        comment.refresh_from_db()
        self.assertEqual(comment.status, "pending")
        confirm_from_token(secret, self.site)
        self.assertEqual(MailJob.objects.filter(kind="confirm").count(), 1)

    def test_guest_publication_always_has_edit_email(self):
        comment = self.guest()
        from commentail.services import confirm_email

        confirm_email(comment.pk)
        moderate(comment.pk, "approve", actor=self.admin)
        moderate(comment.pk, "approve", actor=self.admin)
        self.assertEqual(MailJob.objects.filter(kind="edit").count(), 1)
        self.assertEqual(MailJob.objects.filter(kind="published").count(), 0)

    def test_immediate_registered_publication_sends_no_author_mail(self):
        self.options.moderation = "none"
        self.options.notify_publication = True
        self.options.save()
        comment = submit(self.discussion.pk, text="Immediate", user=self.author)
        self.assertEqual(comment.status, "published")
        self.assertFalse(MailJob.objects.filter(comment=comment).exists())
        self.assertEqual(process_mail(), 0)

    def test_immediate_guest_publication_keeps_edit_link_without_publication_notice(
        self,
    ):
        self.options.moderation = "none"
        self.options.notify_publication = True
        self.options.save()
        comment = self.guest()
        confirm_email(comment.pk)
        comment.refresh_from_db()
        self.assertEqual(comment.status, "published")
        self.assertCountEqual(
            MailJob.objects.filter(comment=comment).values_list("kind", flat=True),
            ["confirm", "edit"],
        )

    def test_moderated_publication_notifies_registered_and_guest_authors_once(self):
        self.options.notify_publication = True
        self.options.save()
        registered = submit(self.discussion.pk, text="Pending", user=self.author)
        guest = self.guest()
        confirm_email(guest.pk)
        for comment in (registered, guest):
            with self.subTest(guest=comment.user_id is None):
                self.assertFalse(
                    MailJob.objects.filter(comment=comment, kind="published").exists()
                )
                moderate(comment.pk, "approve", actor=self.admin)
                moderate(comment.pk, "approve", actor=self.admin)
                self.assertEqual(
                    MailJob.objects.filter(comment=comment, kind="published").count(), 1
                )

    def test_immediate_revision_is_silent_but_moderated_revision_notifies_once(self):
        self.options.moderation = "none"
        self.options.notify_publication = True
        self.options.save()
        comment = submit(self.discussion.pk, text="Original", user=self.author)
        immediate = revise(comment.pk, "Immediate edit", user=self.author)
        self.assertEqual(immediate.status, "approved")
        self.assertFalse(MailJob.objects.filter(revision=immediate).exists())
        self.options.moderation = "all"
        self.options.save()
        pending = revise(comment.pk, "Moderated edit", user=self.author)
        self.assertEqual(pending.status, "pending")
        self.assertFalse(MailJob.objects.filter(revision=pending).exists())
        moderate_revision(pending.pk, "approve", actor=self.admin)
        moderate_revision(pending.pk, "approve", actor=self.admin)
        self.assertEqual(
            MailJob.objects.filter(revision=pending, kind="published").count(), 1
        )

    def test_immediate_reply_notifies_parent_but_not_reply_author(self):
        self.options.moderation = "none"
        self.options.notify_publication = True
        self.options.save()
        parent = submit(
            self.discussion.pk, text="Parent", user=self.author, subscribe=True
        )
        reply = submit(
            self.discussion.pk, text="Reply", user=self.admin, reply_to=parent.pk
        )
        job = MailJob.objects.get(comment=reply)
        self.assertEqual(job.kind, "reply")
        self.assertEqual(job.recipient, parent)
        self.assertFalse(MailJob.objects.filter(kind="published").exists())

    def test_immediate_guest_revision_does_not_send_publication_notice(self):
        from commentail.security import token_secret

        self.options.moderation = "none"
        self.options.notify_publication = True
        self.options.save()
        comment = self.guest()
        confirm_email(comment.pk)
        secret = token_secret(MailJob.objects.get(comment=comment, kind="edit").token)
        revision = revise(
            comment.pk, "Immediate guest edit", edit_token=secret, site=self.site
        )
        self.assertEqual(revision.status, "approved")
        self.assertFalse(MailJob.objects.filter(kind="published").exists())

    def test_discussion_publication_switch_overrides_site_for_reviewed_decisions(self):
        self.options.notify_publication = True
        self.options.save()
        self.discussion.notify_publication = False
        self.discussion.save()
        comment = submit(self.discussion.pk, text="Original", user=self.author)
        moderate(comment.pk, "approve", actor=self.admin)
        revision = revise(comment.pk, "Reviewed edit", user=self.author)
        moderate_revision(revision.pk, "approve", actor=self.admin)
        self.assertFalse(
            MailJob.objects.filter(comment=comment, kind="published").exists()
        )
        self.discussion.notify_publication = True
        self.discussion.save()
        revision = revise(comment.pk, "Another edit", user=self.author)
        moderate_revision(revision.pk, "approve", actor=self.admin)
        self.assertEqual(
            MailJob.objects.filter(revision=revision, kind="published").count(), 1
        )

    def test_reply_mail_has_no_text_and_unsubscribe(self):
        parent = submit(
            self.discussion.pk, text="Parent", user=self.author, subscribe=True
        )
        moderate(parent.pk, "approve", actor=self.admin)
        other = get_user_model().objects.create_user("responder")
        reply = submit(
            self.discussion.pk,
            text="UNIQUE SECRET REPLY TEXT",
            user=other,
            reply_to=parent.pk,
        )
        self.assertFalse(MailJob.objects.filter(kind="reply").exists())
        moderate(reply.pk, "approve", actor=self.admin)
        self.assertEqual(process_mail(), 1)
        message = mail.outbox[-1]
        self.assertNotIn(reply.text, message.body + message.subject)
        self.assertIn("responder", message.body)
        self.assertIn(f"?target={reply.pk}#commentail-{reply.pk}", message.body)
        job = MailJob.objects.get(kind="reply")
        from commentail.security import token_secret

        unsubscribe(token_secret(job.token), self.site)
        self.assertFalse(ReplySubscription.objects.get(comment=parent).enabled)

    def test_hidden_jobs_wait_and_expired_jobs_cancel(self):
        self.guest()
        self.discussion.mode = "hidden"
        self.discussion.save()
        self.assertEqual(process_mail(), 0)
        self.assertEqual(MailJob.objects.get().status, "pending")
        MailJob.objects.update(expires_at=timezone.now())
        self.assertEqual(process_mail(), 0)
        self.assertEqual(MailJob.objects.get().status, "cancelled")

    def test_temporary_failure_retries_without_extending_expiry(self):
        self.guest()
        job = MailJob.objects.get()
        expires = job.expires_at
        with patch("commentail.outbox.deliver", side_effect=TimeoutError("uncertain")):
            self.assertEqual(process_mail(), 0)
        job.refresh_from_db()
        self.assertEqual(job.status, "pending")
        self.assertEqual(job.attempts, 1)
        self.assertEqual(job.expires_at, expires)
        self.assertGreaterEqual(
            job.next_attempt_at, timezone.now() + timedelta(seconds=59)
        )
        MailJob.objects.update(next_attempt_at=timezone.now())
        self.assertEqual(process_mail(), 1)

    def test_permanent_failure_is_not_retried_automatically(self):
        self.guest()
        with patch(
            "commentail.outbox.deliver", side_effect=SMTPDataError(550, b"Rejected")
        ):
            process_mail()
        self.assertEqual(MailJob.objects.get().status, "failed")

    def test_worker_recovers_expired_claim_but_leaves_active_claim_alone(self) -> None:
        self.guest()
        job = MailJob.objects.get()
        claimed = claim_job(job.pk)
        self.assertIsNotNone(claimed)
        self.assertEqual(process_mail(), 0)
        self.assertEqual(len(mail.outbox), 0)
        MailJob.objects.filter(pk=job.pk).update(
            lease_until=timezone.now() - timedelta(seconds=1)
        )
        self.assertEqual(process_mail(), 1)
        job.refresh_from_db()
        self.assertEqual(job.status, "sent")
        self.assertEqual(job.attempts, 2)
        self.assertIsNone(job.lease_until)
        self.assertEqual(len(mail.outbox), 1)

    def test_reclaimed_expired_message_is_cancelled_without_delivery(self) -> None:
        self.guest()
        job = MailJob.objects.get()
        claim_job(job.pk)
        MailJob.objects.filter(pk=job.pk).update(
            lease_until=timezone.now() - timedelta(seconds=1),
            expires_at=timezone.now() - timedelta(seconds=1),
        )
        self.assertEqual(process_mail(), 0)
        job.refresh_from_db()
        self.assertEqual(job.status, "cancelled")
        self.assertIsNone(job.lease_until)
        self.assertEqual(len(mail.outbox), 0)

    def test_uncertain_delivery_retry_keeps_message_id_and_original_deadline(
        self,
    ) -> None:
        self.guest()
        job = MailJob.objects.get()
        deadline = job.expires_at

        def accepted_then_disconnected(message: MailJob) -> None:
            deliver(message)
            raise TimeoutError("Synthetic disconnect after SMTP acceptance")

        with patch("commentail.outbox.deliver", side_effect=accepted_then_disconnected):
            self.assertEqual(process_mail(), 0)
        job.refresh_from_db()
        self.assertEqual(job.status, "pending")
        self.assertEqual(job.error, "TimeoutError")
        MailJob.objects.filter(pk=job.pk).update(next_attempt_at=timezone.now())
        self.assertEqual(process_mail(), 1)
        job.refresh_from_db()
        self.assertEqual(job.expires_at, deadline)
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(
            mail.outbox[0].extra_headers["Message-ID"],
            mail.outbox[1].extra_headers["Message-ID"],
        )
        self.assertEqual(mail.outbox[0].body, mail.outbox[1].body)

    def test_smtp_response_classes_control_retry_without_private_diagnostics(
        self,
    ) -> None:
        for failure, status in [
            (SMTPAuthenticationError(535, b"private credentials detail"), "failed"),
            (SMTPServerDisconnected("private connection detail"), "pending"),
            (SMTPDataError(451, b"private transport detail"), "pending"),
            (SMTPDataError(550, b"private transport detail"), "failed"),
            (
                SMTPRecipientsRefused(
                    {"guest@example.invalid": (450, b"private detail")}
                ),
                "pending",
            ),
            (
                SMTPRecipientsRefused(
                    {"guest@example.invalid": (550, b"private detail")}
                ),
                "failed",
            ),
        ]:
            with self.subTest(failure=type(failure).__name__, status=status):
                comment = self.guest()
                job = MailJob.objects.get(comment=comment)
                with patch("commentail.outbox.deliver", side_effect=failure):
                    self.assertEqual(process_mail(), 0)
                job.refresh_from_db()
                self.assertEqual(job.status, status)
                self.assertEqual(job.error, type(failure).__name__)
                self.assertIsNone(job.lease_until)

    def test_requeue_requires_site_moderation_permission(self):
        self.guest()
        MailJob.objects.update(status="failed")
        with self.assertRaises(DomainError):
            requeue(MailJob.objects.get().pk, actor=self.author)
        requeue(MailJob.objects.get().pk, actor=self.admin)
        self.assertEqual(MailJob.objects.get().status, "pending")

    def test_expired_link_cannot_be_requeued(self):
        self.guest()
        MailJob.objects.update(status="failed", expires_at=timezone.now())
        with self.assertRaises(DomainError):
            requeue(MailJob.objects.get().pk, actor=self.admin)

    def test_account_deletion_cancels_queued_mail_and_subscriptions(self):
        self.options.notify_publication = True
        self.options.save()
        comment = submit(
            self.discussion.pk, text="Message", user=self.author, subscribe=True
        )
        moderate(comment.pk, "approve", actor=self.admin)
        self.author.delete()
        self.assertFalse(ReplySubscription.objects.get(comment=comment).enabled)
        self.assertFalse(MailJob.objects.filter(status="pending").exists())

    def test_guest_edit_link_obeys_domain_window(self):
        from commentail.services import confirm_email

        comment = self.guest()
        confirm_email(comment.pk)
        moderate(comment.pk, "approve", actor=self.admin)
        from commentail.security import token_secret

        secret = token_secret(MailJob.objects.get(kind="edit").token)
        revision = revise(comment.pk, "New", edit_token=secret, site=self.site)
        self.assertEqual(revision.status, "pending")
        with self.assertRaises(DomainError):
            revise(comment.pk, "Again", edit_token=secret, site=self.site)

    def test_unsubscribe_cancels_waiting_reply(self):
        parent = submit(
            self.discussion.pk, text="Parent", user=self.author, subscribe=True
        )
        moderate(parent.pk, "approve", actor=self.admin)
        reply = submit(
            self.discussion.pk, text="Reply", user=self.admin, reply_to=parent.pk
        )
        moderate(reply.pk, "approve", actor=self.admin)
        job = MailJob.objects.get(kind="reply")
        from commentail.security import token_secret

        unsubscribe(token_secret(job.token), self.site)
        self.assertEqual(process_mail(), 0)
        job.refresh_from_db()
        self.assertEqual(job.status, "cancelled")

    def test_lost_page_access_cancels_permanently(self):
        from wagtail.models import PageViewRestriction

        self.guest()
        restriction = PageViewRestriction.objects.create(
            page=self.site.root_page, restriction_type="login"
        )
        self.assertEqual(process_mail(), 0)
        job = MailJob.objects.get()
        self.assertEqual(job.status, "cancelled")
        restriction.delete()
        self.assertEqual(process_mail(), 0)

    def test_maximum_four_automatic_attempts(self):
        self.guest()
        with patch("commentail.outbox.deliver", side_effect=TimeoutError()):
            for _ in range(4):
                MailJob.objects.update(next_attempt_at=timezone.now())
                process_mail()
        job = MailJob.objects.get()
        self.assertEqual(job.attempts, 4)
        self.assertEqual(job.status, "failed")

    def test_revision_rejection_reason_is_only_in_author_mail(self):
        from commentail.services import moderate_revision

        self.options.notify_rejection = True
        self.options.save()
        comment = submit(self.discussion.pk, text="Original", user=self.author)
        moderate(comment.pk, "approve", actor=self.admin)
        revision = revise(comment.pk, "New", user=self.author)
        moderate_revision(
            revision.pk, "reject", actor=self.admin, reason="Please explain"
        )
        self.assertEqual(process_mail(), 1)
        self.assertIn("Please explain", mail.outbox[-1].body)
        self.assertNotIn("New", mail.outbox[-1].body)
