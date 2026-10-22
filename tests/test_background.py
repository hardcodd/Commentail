"""Host tasks retain the outbox and maintenance contracts without invoking a CLI."""

from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.core import mail
from django.core.management import call_command
from django.db import transaction
from django.db.models import QuerySet
from django.db.models.signals import pre_delete
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

    def test_cleanup_commits_multiple_batches_and_preserves_active_records(self):
        now = timezone.now()
        old = now - timedelta(days=2)
        future = now + timedelta(days=1)
        models = (CaptchaChallenge, GuestGrant, FormTicket, RateEvent)
        for index in range(501):
            digest = f"{index:064x}"
            CaptchaChallenge.objects.create(
                site=self.site, session_digest=digest, answer=2, expires_at=old
            )
            GuestGrant.objects.create(
                site=self.site,
                digest=digest,
                email="guest@example.invalid",
                confirmed_at=old,
                expires_at=old,
            )
            FormTicket.objects.create(
                digest=digest,
                discussion=self.discussion,
                session_digest="s" * 64,
                expires_at=old,
            )
        RateEvent.objects.bulk_create(
            [
                RateEvent(site=self.site, kind="post", subject_digest="a" * 64)
                for _ in range(501)
            ]
        )
        RateEvent.objects.update(created_at=old)
        self.ticket(future, "z")
        CaptchaChallenge.objects.create(
            site=self.site, session_digest="z" * 64, answer=2, expires_at=future
        )
        GuestGrant.objects.create(
            site=self.site,
            digest="z" * 64,
            email="guest@example.invalid",
            confirmed_at=now,
            expires_at=future,
        )
        live_rate = RateEvent.objects.create(
            site=self.site, kind="post", subject_digest="z" * 64
        )
        kept = {
            model: set(
                model.objects.filter(expires_at=future).values_list("pk", flat=True)
            )
            for model in models[:-1]
        }
        kept[RateEvent] = {live_rate.pk}
        seen = {model: [] for model in models}
        committed = {model: [] for model in models}

        def observe_delete(sender, instance, using, **kwargs):
            # The second batch must begin after the first one's commit callbacks.
            self.assertLess(len(seen[sender]) - len(committed[sender]), 500)
            seen[sender].append(instance.pk)
            transaction.on_commit(
                lambda pk=instance.pk: committed[sender].append(pk), using=using
            )

        for model in models:
            pre_delete.connect(observe_delete, sender=model)
        try:
            with patch("commentail.background.timezone.now", return_value=now):
                self.assertEqual(process_pending(), {"sent": 0, "removed": 0})
        finally:
            for model in models:
                pre_delete.disconnect(observe_delete, sender=model)
        for model in models:
            with self.subTest(model=model.__name__):
                self.assertEqual(len(seen[model]), 501)
                self.assertEqual(committed[model], seen[model])
                self.assertEqual(
                    set(model.objects.values_list("pk", flat=True)),
                    kept[model],
                )
                self.assertEqual(model.objects.count(), 1)
        self.assertTrue(RateEvent.objects.filter(pk=live_rate.pk).exists())

    def test_cleanup_failure_preserves_previously_committed_batches(self):
        old = timezone.now() - timedelta(days=2)
        for _ in range(5):
            RateEvent.objects.create(
                site=self.site, kind="post", subject_digest="a" * 64
            )
        RateEvent.objects.update(created_at=old)
        identifiers = list(
            RateEvent.objects.order_by("pk").values_list("pk", flat=True)
        )

        def fail_second_batch(sender, instance, **kwargs):
            if instance.pk == identifiers[2]:
                raise RuntimeError("Synthetic cleanup failure")

        pre_delete.connect(fail_second_batch, sender=RateEvent)
        try:
            with (
                patch("commentail.background.CLEANUP_BATCH_SIZE", 2),
                self.assertRaisesMessage(RuntimeError, "Synthetic cleanup failure"),
            ):
                process_pending()
        finally:
            pre_delete.disconnect(fail_second_batch, sender=RateEvent)
        self.assertEqual(
            list(RateEvent.objects.order_by("pk").values_list("pk", flat=True)),
            identifiers[2:],
        )

    def test_cleanup_retains_existing_expiry_boundaries(self):
        from commentail.limits import retention_seconds

        now = timezone.now()
        self.ticket(now)
        CaptchaChallenge.objects.create(
            site=self.site, session_digest="a" * 64, answer=2, expires_at=now
        )
        GuestGrant.objects.create(
            site=self.site,
            digest="a" * 64,
            email="guest@example.invalid",
            confirmed_at=now,
            expires_at=now,
        )
        rate = RateEvent.objects.create(
            site=self.site, kind="post", subject_digest="a" * 64
        )
        RateEvent.objects.filter(pk=rate.pk).update(
            created_at=now - timedelta(seconds=retention_seconds())
        )
        with patch("commentail.background.timezone.now", return_value=now):
            process_pending()
        for model in (CaptchaChallenge, GuestGrant, FormTicket):
            self.assertFalse(model.objects.exists())
        self.assertTrue(RateEvent.objects.filter(pk=rate.pk).exists())

    def test_cleanup_rechecks_expiry_before_deleting_selected_records(self):
        now = timezone.now()
        ticket = self.ticket(now - timedelta(minutes=1))
        original_delete = QuerySet.delete

        def renew_then_delete(query):
            if query.model is FormTicket:
                FormTicket.objects.filter(pk=ticket.pk).update(
                    expires_at=now + timedelta(hours=1)
                )
            return original_delete(query)

        with patch.object(QuerySet, "delete", renew_then_delete):
            process_pending()
        self.assertTrue(FormTicket.objects.filter(pk=ticket.pk).exists())

    def test_cleanup_keeps_one_cutoff_when_time_advances_between_batches(self):
        now = timezone.now()
        self.ticket(now - timedelta(minutes=1), "a")
        later_ticket = self.ticket(now + timedelta(minutes=1), "b")

        with patch("commentail.background.timezone.now", return_value=now) as clock:

            def advance_clock(sender, instance, **kwargs):
                transaction.on_commit(
                    lambda: setattr(clock, "return_value", now + timedelta(hours=1))
                )

            pre_delete.connect(advance_clock, sender=FormTicket)
            try:
                with patch("commentail.background.CLEANUP_BATCH_SIZE", 1):
                    process_pending()
            finally:
                pre_delete.disconnect(advance_clock, sender=FormTicket)
        self.assertEqual(
            list(FormTicket.objects.values_list("pk", flat=True)), [later_ticket.pk]
        )

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
