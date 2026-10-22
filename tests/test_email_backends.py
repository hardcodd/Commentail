"""Exercise Django's transport contract without SMTP or external services."""

from datetime import timedelta
from io import StringIO
from pathlib import Path
from smtplib import SMTPDataError
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core import mail
from django.core.mail.backends.base import BaseEmailBackend
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from wagtail.models import Site

from commentail.admission import email_configured
from commentail.models import CaptchaChallenge, Discussion, MailJob
from commentail.outbox import process_mail
from commentail.services import submit


class StrictBackend(BaseEmailBackend):
    """A provider backend accepting only Django's standard constructor argument."""

    def __init__(self, fail_silently=False):
        super().__init__(fail_silently=fail_silently)

    def send_messages(self, email_messages):
        for message in email_messages:
            # Serialize as a provider would, exercising headers and MIME alternatives.
            message.message()
            mail.outbox.append(message)
        return len(email_messages)


class ProviderError(Exception):
    """A synthetic transport failure unrelated to smtplib or OSError."""


class ConfigurationTests(SimpleTestCase):
    @override_settings(
        EMAIL_BACKEND="tests.test_email_backends.StrictBackend", EMAIL_HOST=""
    )
    def test_backend_availability_does_not_construct_or_contact_transport(self):
        with patch.object(
            StrictBackend, "__init__", side_effect=AssertionError("No I/O on GET")
        ):
            self.assertTrue(email_configured())

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend", EMAIL_HOST=""
    )
    def test_smtp_still_requires_host(self):
        self.assertFalse(email_configured())

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend")
    def test_implicit_django_localhost_does_not_enable_smtp(self):
        self.assertFalse(email_configured())

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
        EMAIL_HOST="smtp.invalid",
    )
    def test_smtp_with_explicit_host_is_available(self):
        self.assertTrue(email_configured())


@override_settings(
    EMAIL_BACKEND="tests.test_email_backends.StrictBackend", EMAIL_HOST=""
)
class EmailBackendTests(TestCase):
    def setUp(self):
        self.site = Site.objects.get(is_default_site=True)
        self.discussion = Discussion.objects.create(
            site=self.site, page=self.site.root_page
        )

    def guest(self):
        return submit(
            self.discussion.pk,
            text="Guest",
            guest_name="Guest",
            guest_email="guest@example.invalid",
        )

    def test_guest_form_submission_and_worker_use_non_smtp_backend(self):
        response = self.client.get(
            reverse("commentail:discussion", args=[self.site.root_page.pk])
        )
        self.assertTrue(response.context["can_post"])
        challenge = response.context["captcha"]
        self.assertIsNotNone(challenge)
        with patch.object(
            StrictBackend, "send_messages", wraps=StrictBackend().send_messages
        ) as sending:
            response = self.client.post(
                reverse("commentail:submit", args=[self.site.root_page.pk]),
                {
                    "key": response.context["form_key"],
                    "text": "A guest using a provider backend",
                    "name": "Guest",
                    "email": "guest@example.invalid",
                    "challenge": str(challenge.id),
                    "answer": str(CaptchaChallenge.objects.get(pk=challenge.id).answer),
                },
            )
            self.assertEqual(response.status_code, 302)
            sending.assert_not_called()
            self.assertEqual(process_mail(), 1)
        job = MailJob.objects.get()
        self.assertEqual(job.comment.status, "awaiting_email")
        self.assertEqual(job.status, "sent")
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["guest@example.invalid"])
        self.assertTrue(mail.outbox[0].alternatives)

    def test_provider_failure_does_not_abort_batch_and_retry_preserves_deadline(self):
        first, second = self.guest(), self.guest()
        job = MailJob.objects.get(comment=first)
        deadline = job.expires_at
        send = StrictBackend.send_messages

        def fail_first(backend, messages):
            if (
                messages[0]
                .extra_headers["Message-ID"]
                .startswith(f"<commentail-{job.pk}@")
            ):
                raise ProviderError(
                    "private api-key guest@example.invalid token=secret"
                )
            return send(backend, messages)

        with patch.object(StrictBackend, "send_messages", fail_first):
            self.assertEqual(process_mail(), 1)
        job.refresh_from_db()
        self.assertEqual(job.status, "pending")
        self.assertEqual(job.error, "ProviderError")
        self.assertIsNone(job.lease_until)
        self.assertEqual(MailJob.objects.get(comment=second).status, "sent")
        MailJob.objects.filter(pk=job.pk).update(next_attempt_at=timezone.now())
        self.assertEqual(process_mail(), 1)
        job.refresh_from_db()
        self.assertEqual(job.expires_at, deadline)
        self.assertEqual(job.status, "sent")

    def test_unknown_provider_failure_exhausts_existing_retry_budget(self):
        self.guest()
        job = MailJob.objects.get()
        deadline = job.expires_at
        with patch.object(
            StrictBackend, "send_messages", side_effect=ProviderError("private detail")
        ):
            for attempt in range(1, 5):
                self.assertEqual(process_mail(), 0)
                job.refresh_from_db()
                self.assertEqual(job.attempts, attempt)
                self.assertEqual(job.status, "failed" if attempt == 4 else "pending")
                self.assertEqual(job.error, "ProviderError")
                self.assertEqual(job.expires_at, deadline)
                MailJob.objects.filter(pk=job.pk).update(next_attempt_at=timezone.now())
        self.assertEqual(process_mail(), 0)

    def test_no_reported_delivery_retries_instead_of_claiming_success(self):
        for result in (0, None):
            with self.subTest(result=result):
                comment = self.guest()
                with patch.object(StrictBackend, "send_messages", return_value=result):
                    self.assertEqual(process_mail(), 0)
                job = MailJob.objects.get(comment=comment)
                self.assertEqual(job.status, "pending")
                self.assertEqual(job.error, "OSError")

    def test_backend_initialization_failure_is_retried_without_diagnostics(self):
        self.guest()
        with patch.object(
            StrictBackend, "__init__", side_effect=ProviderError("private key")
        ):
            self.assertEqual(process_mail(), 0)
        job = MailJob.objects.get()
        self.assertEqual(job.status, "pending")
        self.assertEqual(job.error, "ProviderError")
        self.assertIsNone(job.lease_until)

    def test_django_development_backends_work_without_smtp_settings(self):
        for backend in ("locmem", "console", "filebased", "dummy"):
            with self.subTest(backend=backend), TemporaryDirectory() as directory:
                with (
                    override_settings(
                        EMAIL_BACKEND=f"django.core.mail.backends.{backend}.EmailBackend",
                        EMAIL_FILE_PATH=directory,
                    ),
                    patch("sys.stdout", new_callable=StringIO) as console,
                ):
                    self.assertTrue(email_configured())
                    comment = self.guest()
                    self.assertEqual(process_mail(), 1)
                    if backend == "console":
                        self.assertIn("guest@example.invalid", console.getvalue())
                    if backend == "filebased":
                        self.assertEqual(len(list(Path(directory).glob("*.log"))), 1)
                self.assertEqual(MailJob.objects.get(comment=comment).status, "sent")

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
        EMAIL_HOST="smtp.invalid",
    )
    def test_smtp_timeout_remains_bounded_by_lease_and_respects_shorter_setting(self):
        from django.core.mail.backends.smtp import EmailBackend

        observed = []

        def capture(backend, messages):
            observed.append(backend.timeout)
            return len(messages)

        with patch.object(EmailBackend, "send_messages", capture):
            for configured, expected in ((None, 30), (7, 7), (120, 30)):
                with override_settings(EMAIL_TIMEOUT=configured):
                    self.guest()
                    self.assertEqual(process_mail(), 1)
                    self.assertEqual(observed[-1], expected)
            with override_settings(COMMENTAIL={"default": {"MAIL_LEASE_SECONDS": 10}}):
                self.guest()
                self.assertEqual(process_mail(), 1)
                self.assertEqual(observed[-1], 5)

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
        EMAIL_HOST="smtp.invalid",
    )
    def test_smtp_transport_errors_keep_permanent_and_temporary_classification(self):
        from django.core.mail.backends.smtp import EmailBackend

        for code, status in ((451, "pending"), (550, "failed")):
            with self.subTest(code=code):
                comment = self.guest()
                with patch.object(
                    EmailBackend,
                    "send_messages",
                    side_effect=SMTPDataError(code, b"private detail"),
                ):
                    self.assertEqual(process_mail(), 0)
                job = MailJob.objects.get(comment=comment)
                self.assertEqual(job.status, status)
                self.assertEqual(job.error, "SMTPDataError")

    def test_expired_job_never_reaches_provider(self):
        self.guest()
        MailJob.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        with patch.object(StrictBackend, "send_messages") as sending:
            self.assertEqual(process_mail(), 0)
            sending.assert_not_called()
        self.assertEqual(MailJob.objects.get().status, "cancelled")
