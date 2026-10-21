"""Host tasks retain the outbox and maintenance contracts without invoking a CLI."""

from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.core import mail
from django.core.management import call_command
from django.db import transaction
from django.db.transaction import TransactionManagementError
from django.test import SimpleTestCase, TransactionTestCase
from django.utils import timezone
from wagtail.models import Locale, Page, Site

from commentail.background import process_pending
from commentail.models import (
    CaptchaChallenge,
    Comment,
    Discussion,
    FormTicket,
    GuestGrant,
    MailJob,
    RateEvent,
)
from commentail.outbox import claim_job
from commentail.services import submit


class BatchValidationTests(SimpleTestCase):
    def test_invalid_limits_fail_before_database_access(self):
        for value in (0, -1, True, False, None, "10", 1.5):
            with self.subTest(value=value), self.assertRaises(ValueError):
                process_pending(mail_limit=value)


class HostTaskTests(TransactionTestCase):
    def setUp(self):
        Locale.objects.get_or_create(language_code="en")
        root = Page.get_first_root_node()
        if root is None:
            root = Page.add_root(title="Synthetic root", slug="root")
        self.site = Site.objects.create(hostname="background.invalid", root_page=root)
        self.discussion = Discussion.objects.create(site=self.site, page=root)

    def guest(self, text="Guest"):
        return submit(
            self.discussion.pk,
            text=text,
            guest_name="Guest",
            guest_email="guest@example.invalid",
        )

    def ticket(self, expiry, digest="a"):
        return FormTicket.objects.create(
            digest=digest * 64,
            discussion=self.discussion,
            session_digest="s" * 64,
            expires_at=expiry,
        )

    def test_task_sends_mail_and_cleans_only_expired_records(self):
        now = timezone.now()
        old = now - timedelta(days=2)
        future = now + timedelta(days=1)
        expired_guest = self.guest("Expired")
        Comment.objects.filter(pk=expired_guest.pk).update(created_at=old)
        live_guest = self.guest()
        for expiry, digest in ((old, "a"), (future, "b")):
            self.ticket(expiry, digest)
            CaptchaChallenge.objects.create(
                site=self.site,
                session_digest=digest * 64,
                answer=2,
                expires_at=expiry,
            )
            GuestGrant.objects.create(
                site=self.site,
                digest=digest * 64,
                email="guest@example.invalid",
                confirmed_at=now,
                expires_at=expiry,
            )
        stale_rate = RateEvent.objects.create(
            site=self.site, kind="post", subject_digest="a" * 64
        )
        RateEvent.objects.filter(pk=stale_rate.pk).update(created_at=old)
        live_rate = RateEvent.objects.create(
            site=self.site, kind="post", subject_digest="b" * 64
        )

        result = process_pending()

        self.assertEqual(result, {"sent": 1, "removed": 1})
        self.assertFalse(Comment.objects.filter(pk=expired_guest.pk).exists())
        self.assertTrue(Comment.objects.filter(pk=live_guest.pk).exists())
        self.assertEqual(FormTicket.objects.count(), 1)
        self.assertEqual(FormTicket.objects.get().digest, "b" * 64)
        self.assertEqual(CaptchaChallenge.objects.count(), 1)
        self.assertEqual(CaptchaChallenge.objects.get().expires_at, future)
        self.assertEqual(GuestGrant.objects.count(), 1)
        self.assertEqual(GuestGrant.objects.get().expires_at, future)
        self.assertEqual(
            list(RateEvent.objects.values_list("pk", flat=True)), [live_rate.pk]
        )
        self.assertEqual(MailJob.objects.get().status, "sent")
        self.assertEqual(len(mail.outbox), 1)

    def test_bounded_batches_and_duplicate_tasks_do_not_resend(self):
        self.guest("First")
        self.guest("Second")
        self.assertEqual(process_pending(mail_limit=1), {"sent": 1, "removed": 0})
        self.assertEqual(MailJob.objects.filter(status="pending").count(), 1)
        self.assertEqual(process_pending(mail_limit=1), {"sent": 1, "removed": 0})
        self.assertEqual(process_pending(), {"sent": 0, "removed": 0})
        self.assertEqual(len(mail.outbox), 2)

    def test_active_claim_is_skipped_and_expired_lease_is_recovered(self):
        self.guest()
        job = MailJob.objects.get()
        claimed = claim_job(job.pk)
        self.assertIsNotNone(claimed)
        self.assertEqual(process_pending()["sent"], 0)
        with patch(
            "commentail.outbox.timezone.now",
            return_value=claimed.lease_until + timedelta(seconds=1),
        ):
            self.assertEqual(process_pending()["sent"], 1)
        self.assertEqual(len(mail.outbox), 1)

    def test_provider_retry_keeps_original_proof_and_deadline(self):
        self.guest()
        original = MailJob.objects.get()
        with patch(
            "django.core.mail.backends.locmem.EmailBackend.send_messages",
            side_effect=OSError("private diagnostics"),
        ):
            self.assertEqual(process_pending()["sent"], 0)
        job = MailJob.objects.get()
        self.assertEqual(
            (job.status, job.attempts, job.error), ("pending", 1, "OSError")
        )
        self.assertEqual(
            (job.token_id, job.expires_at), (original.token_id, original.expires_at)
        )
        self.assertEqual(process_pending()["sent"], 0)
        with patch(
            "commentail.outbox.timezone.now",
            return_value=job.next_attempt_at + timedelta(seconds=1),
        ):
            self.assertEqual(process_pending()["sent"], 1)
        job.refresh_from_db()
        self.assertEqual(
            (job.token_id, job.expires_at), (original.token_id, original.expires_at)
        )

    def test_caller_transaction_is_rejected_before_cleanup_or_mail(self):
        self.guest()
        ticket = self.ticket(timezone.now() - timedelta(minutes=1))
        with transaction.atomic(), self.assertRaises(TransactionManagementError):
            process_pending()
        self.assertTrue(FormTicket.objects.filter(pk=ticket.pk).exists())
        self.assertEqual(MailJob.objects.get().status, "pending")
        self.assertEqual(len(mail.outbox), 0)

    def test_existing_command_preserves_output_and_full_processing(self):
        self.guest()
        ticket = self.ticket(timezone.now() - timedelta(minutes=1))
        output = StringIO()
        call_command("process_commentail", stdout=output)
        self.assertEqual(
            output.getvalue(), "Sent 1 messages; removed 0 unconfirmed comments.\n"
        )
        self.assertFalse(FormTicket.objects.filter(pk=ticket.pk).exists())
        self.assertEqual(MailJob.objects.get().status, "sent")
