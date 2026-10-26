"""Verify independent Commentail delivery through public form and worker paths."""

from io import StringIO
from typing import ClassVar
from unittest.mock import patch

from django.conf import settings
from django.core import mail
from django.core.exceptions import ImproperlyConfigured
from django.core.mail import send_mail
from django.core.mail.backends.base import BaseEmailBackend
from django.core.mail.backends.smtp import EmailBackend as SMTPBackend
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from wagtail.models import Locale, Page, Site

from commentail.admission import email_configured
from commentail.background import process_pending
from commentail.checks import check_settings
from commentail.models import CaptchaChallenge, Discussion, MailJob
from commentail.outbox import process_mail
from commentail.services import submit
from tests.test_smtp_chain import smtp_receiver

BACKEND = "tests.test_independent_email.ProviderBackend"
SMTP_BACKEND = "django.core.mail.backends.smtp.EmailBackend"


class ProviderError(Exception):
    """A provider failure whose private details must stay outside queue status."""


class ProviderBackend(BaseEmailBackend):
    """Synthetic transport with constructor options and a separate mailbox."""

    messages: ClassVar[list[mail.EmailMessage]] = []
    configurations: ClassVar[list[tuple[str, int, bool]]] = []

    def __init__(self, fail_silently=False, *, api_key="", timeout=12):
        super().__init__(fail_silently=fail_silently)
        self.configurations.append((api_key, timeout, fail_silently))

    def send_messages(self, email_messages):
        for message in email_messages:
            message.message()
            self.messages.append(message)
        return len(email_messages)


class CustomSMTPBackend(SMTPBackend):
    """Exercise standard SMTP handling alongside a subclass-specific option."""

    def __init__(self, *, token=None, **kwargs):
        super().__init__(**kwargs)
        self.token = token


class IndependentEmailConfigurationTests(SimpleTestCase):
    @override_settings(
        EMAIL_BACKEND=SMTP_BACKEND,
        EMAIL_HOST="",
        COMMENTAIL_EMAIL={"BACKEND": BACKEND, "OPTIONS": {"api_key": "private"}},
    )
    def test_checks_and_guest_availability_never_construct_provider(self):
        with patch.object(
            ProviderBackend, "__init__", side_effect=AssertionError("No network on GET")
        ):
            self.assertEqual(check_settings(None), [])
            self.assertTrue(email_configured())

    @override_settings(EMAIL_BACKEND=SMTP_BACKEND, EMAIL_HOST="host.invalid")
    def test_smtp_host_option_overrides_host_availability(self):
        for host, expected in (("comments.invalid", True), ("", False), (None, True)):
            with (
                self.subTest(host=host),
                override_settings(
                    COMMENTAIL_EMAIL={
                        "BACKEND": SMTP_BACKEND,
                        "OPTIONS": {"host": host},
                    }
                ),
            ):
                self.assertEqual(email_configured(), expected)

    @override_settings(EMAIL_BACKEND=SMTP_BACKEND)
    def test_implicit_localhost_does_not_enable_independent_smtp(self):
        with override_settings(COMMENTAIL_EMAIL={"BACKEND": SMTP_BACKEND}):
            self.assertFalse(email_configured())
        with override_settings(
            COMMENTAIL_EMAIL={
                "BACKEND": SMTP_BACKEND,
                "OPTIONS": {"host": "comments.invalid"},
            }
        ):
            self.assertTrue(email_configured())

    def test_invalid_configuration_fails_checks_without_secret_values(self):
        cases = (
            "private-secret",
            [],
            {"private-secret": "private-secret"},
            {"BACKEND": "private-secret"},
            {"BACKEND": "missing.private-secret.Backend"},
            {"BACKEND": "builtins.str"},
            {"BACKEND": "tests.test_independent_email.send_mail"},
            {"BACKEND": 12},
            {"BACKEND": ""},
            {"OPTIONS": {"api_key": "private-secret"}},
            {"BACKEND": BACKEND, "OPTIONS": "private-secret"},
            {"BACKEND": BACKEND, "OPTIONS": {1: "private-secret"}},
            {"BACKEND": BACKEND, "OPTIONS": {"fail_silently": True}},
            {"BACKEND": BACKEND, "OPTIONS": {"backend": "private-secret"}},
            {"FROM_EMAIL": ""},
            {"FROM_EMAIL": "   "},
            {"FROM_EMAIL": 12},
            {"FROM_EMAIL": "private-secret\nBcc: injected@example.invalid"},
            {"FROM_EMAIL": "private-secret\rBcc: injected@example.invalid"},
            {"FROM_EMAIL": "private-secret\x00"},
        )
        for configuration in cases:
            with (
                self.subTest(configuration=configuration),
                override_settings(COMMENTAIL_EMAIL=configuration),
            ):
                errors = check_settings(None)
                self.assertTrue(errors)
                self.assertTrue(all(error.id == "commentail.E001" for error in errors))
                self.assertNotIn("private-secret", str(errors))
                with self.assertRaises(ImproperlyConfigured) as failure:
                    email_configured()
                self.assertNotIn("private-secret", str(failure.exception))

    def test_invalid_smtp_options_fail_before_transport_construction(self):
        cases = (
            {"host": 12},
            {"username": []},
            {"password": {}},
            {"ssl_keyfile": True},
            {"ssl_certfile": 12},
            {"port": 0},
            {"port": 65536},
            {"port": "587"},
            {"port": True},
            {"timeout": 0},
            {"timeout": -1},
            {"timeout": "private-secret"},
            {"timeout": True},
            {"timeout": float("inf")},
            {"timeout": float("nan")},
            {"use_tls": "private-secret"},
            {"use_ssl": 1},
            {"use_tls": True, "use_ssl": True},
        )
        with patch.object(SMTPBackend, "__init__") as constructor:
            for options in cases:
                with (
                    self.subTest(options=options),
                    override_settings(
                        COMMENTAIL_EMAIL={"BACKEND": SMTP_BACKEND, "OPTIONS": options}
                    ),
                ):
                    errors = check_settings(None)
                    self.assertTrue(errors)
                    self.assertNotIn("private-secret", str(errors))
                    with self.assertRaises(ImproperlyConfigured):
                        email_configured()
            constructor.assert_not_called()

    @override_settings(EMAIL_USE_TLS=True, EMAIL_USE_SSL=False)
    def test_smtp_tls_conflict_considers_inherited_django_settings(self):
        with override_settings(
            COMMENTAIL_EMAIL={"BACKEND": SMTP_BACKEND, "OPTIONS": {"use_ssl": True}}
        ):
            self.assertTrue(check_settings(None))
        with override_settings(
            COMMENTAIL_EMAIL={
                "BACKEND": SMTP_BACKEND,
                "OPTIONS": {"use_tls": False, "use_ssl": True},
            }
        ):
            self.assertEqual(check_settings(None), [])


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="Site <site@example.invalid>",
)
class IndependentEmailDeliveryTests(TestCase):
    def setUp(self):
        ProviderBackend.messages = []
        ProviderBackend.configurations = []
        self.site = Site.objects.get(is_default_site=True)
        self.discussion = Discussion.objects.create(
            site=self.site, page=self.site.root_page
        )

    def guest(self):
        return submit(
            self.discussion.pk,
            text="Independent mail",
            guest_name="Guest",
            guest_email="guest@example.invalid",
        )

    @override_settings(
        COMMENTAIL_EMAIL={
            "BACKEND": BACKEND,
            "OPTIONS": {"api_key": "synthetic-secret", "timeout": 8},
            "FROM_EMAIL": "Comments <comments@example.invalid>",
        }
    )
    def test_commentail_and_host_mail_use_independent_transports_and_senders(self):
        send_mail("Site message", "Site body", None, ["host@example.invalid"])
        self.guest()
        self.assertEqual(process_mail(), 1)
        send_mail("Another site message", "Site body", None, ["host@example.invalid"])

        self.assertEqual(len(mail.outbox), 2)
        self.assertTrue(
            all(
                message.from_email == "Site <site@example.invalid>"
                for message in mail.outbox
            )
        )
        self.assertEqual(len(ProviderBackend.messages), 1)
        message = ProviderBackend.messages[0]
        self.assertEqual(message.from_email, "Comments <comments@example.invalid>")
        self.assertEqual(message.to, ["guest@example.invalid"])
        self.assertTrue(message.alternatives)
        self.assertEqual(
            ProviderBackend.configurations, [("synthetic-secret", 8, False)]
        )

    def test_empty_or_null_overrides_keep_existing_transport_and_sender(self):
        for configuration in ({}, {"BACKEND": None, "FROM_EMAIL": None}):
            with (
                self.subTest(configuration=configuration),
                override_settings(COMMENTAIL_EMAIL=configuration),
            ):
                self.guest()
                self.assertEqual(process_mail(), 1)
                self.assertEqual(
                    mail.outbox[-1].from_email, "Site <site@example.invalid>"
                )
        self.assertEqual(ProviderBackend.messages, [])

    @override_settings(COMMENTAIL_EMAIL={"FROM_EMAIL": "comments@example.invalid"})
    def test_sender_can_be_overridden_without_changing_transport(self):
        self.guest()
        self.assertEqual(process_mail(), 1)
        self.assertEqual(mail.outbox[0].from_email, "comments@example.invalid")

    @override_settings(COMMENTAIL_EMAIL={"BACKEND": BACKEND})
    def test_backend_can_be_overridden_without_changing_sender(self):
        self.guest()
        self.assertEqual(process_mail(), 1)
        self.assertEqual(
            ProviderBackend.messages[0].from_email, "Site <site@example.invalid>"
        )

    @override_settings(
        EMAIL_BACKEND=SMTP_BACKEND, EMAIL_HOST="", COMMENTAIL_EMAIL={"BACKEND": BACKEND}
    )
    def test_guest_form_and_submission_use_independent_backend_availability(self):
        response = self.client.get(
            reverse("commentail:discussion", args=[self.site.root_page.pk])
        )
        self.assertTrue(response.context["can_post"])
        challenge = response.context["captcha"]
        response = self.client.post(
            reverse("commentail:submit", args=[self.site.root_page.pk]),
            {
                "key": response.context["form_key"],
                "text": "Guest using independent provider",
                "name": "Guest",
                "email": "guest@example.invalid",
                "challenge": str(challenge.id),
                "answer": str(CaptchaChallenge.objects.get(pk=challenge.id).answer),
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(ProviderBackend.messages, [])
        self.assertEqual(process_mail(), 1)
        self.assertEqual(MailJob.objects.get().status, "sent")

    @override_settings(
        COMMENTAIL_EMAIL={"BACKEND": SMTP_BACKEND, "OPTIONS": {"host": ""}}
    )
    def test_unavailable_independent_smtp_disables_guests_despite_working_host_backend(
        self,
    ):
        response = self.client.get(
            reverse("commentail:discussion", args=[self.site.root_page.pk])
        )
        self.assertFalse(response.context["can_post"])
        self.assertIsNone(response.context["captcha"])

    @override_settings(EMAIL_HOST="host.invalid")
    def test_empty_independent_smtp_host_never_falls_back_for_existing_jobs(self):
        for host in ("", "   "):
            with (
                self.subTest(host=host),
                override_settings(
                    COMMENTAIL_EMAIL={
                        "BACKEND": SMTP_BACKEND,
                        "OPTIONS": {"host": host},
                    }
                ),
                patch.object(SMTPBackend, "__init__") as constructor,
            ):
                comment = self.guest()
                self.assertEqual(process_mail(), 0)
                job = MailJob.objects.get(comment=comment)
                self.assertEqual(job.status, "pending")
                self.assertEqual(job.error, "ImproperlyConfigured")
                self.assertIsNone(job.lease_until)
                constructor.assert_not_called()
        self.assertEqual(mail.outbox, [])

    def test_real_smtp_uses_commentail_options_while_host_uses_locmem(self):
        with smtp_receiver() as received:
            port = settings.EMAIL_PORT
            with override_settings(
                EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
                EMAIL_HOST="host.invalid",
                COMMENTAIL_EMAIL={
                    "BACKEND": SMTP_BACKEND,
                    "OPTIONS": {
                        "host": "127.0.0.1",
                        "port": port,
                        "username": "",
                        "password": "",
                        "use_tls": False,
                        "use_ssl": False,
                        "timeout": 3,
                    },
                    "FROM_EMAIL": "Comments <comments@example.invalid>",
                },
            ):
                send_mail("Host before", "Host body", None, ["host@example.invalid"])
                self.guest()
                self.assertEqual(process_mail(), 1)
                send_mail("Host after", "Host body", None, ["host@example.invalid"])
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]["From"], "Comments <comments@example.invalid>")
        self.assertEqual(received[0]["To"], "guest@example.invalid")
        self.assertEqual(received[0].get_content_type(), "multipart/alternative")
        self.assertEqual(len(mail.outbox), 2)
        self.assertTrue(
            all(
                message.from_email == "Site <site@example.invalid>"
                for message in mail.outbox
            )
        )
        self.assertEqual(MailJob.objects.get().status, "sent")

    def test_independent_smtp_receives_options_and_bounded_timeout(self):
        observed = []

        def capture(backend, messages):
            observed.append(backend)
            return len(messages)

        options = {
            "host": "comments.invalid",
            "port": 2525,
            "username": "comments-user",
            "password": "synthetic-password",
            "use_tls": True,
            "use_ssl": False,
        }
        with patch.object(SMTPBackend, "send_messages", capture):
            for timeout, expected in ((None, 30), (7, 7), (120, 30), (10**1000, 30)):
                with (
                    self.subTest(timeout=timeout),
                    override_settings(
                        COMMENTAIL_EMAIL={
                            "BACKEND": SMTP_BACKEND,
                            "OPTIONS": {**options, "timeout": timeout},
                        }
                    ),
                ):
                    self.guest()
                    self.assertEqual(process_mail(), 1)
                    backend = observed[-1]
                    self.assertEqual(backend.timeout, expected)
                    self.assertEqual(backend.host, "comments.invalid")
                    self.assertEqual(backend.port, 2525)
                    self.assertEqual(backend.username, "comments-user")
                    self.assertEqual(backend.password, "synthetic-password")
                    self.assertTrue(backend.use_tls)
                    self.assertFalse(backend.use_ssl)
                    self.assertFalse(backend.fail_silently)
            with override_settings(
                COMMENTAIL={"default": {"MAIL_LEASE_SECONDS": 10}},
                COMMENTAIL_EMAIL={"BACKEND": SMTP_BACKEND, "OPTIONS": options},
            ):
                self.guest()
                self.assertEqual(process_mail(), 1)
                self.assertEqual(observed[-1].timeout, 5)
        self.assertEqual(mail.outbox, [])

    @override_settings(
        EMAIL_HOST="host.invalid",
        EMAIL_PORT=2526,
        EMAIL_HOST_USER="host-user",
        EMAIL_HOST_PASSWORD="synthetic-host-password",
        EMAIL_USE_TLS=False,
        EMAIL_USE_SSL=True,
        EMAIL_TIMEOUT=4.5,
        COMMENTAIL_EMAIL={"BACKEND": SMTP_BACKEND},
    )
    def test_omitted_smtp_options_inherit_django_settings(self):
        observed = []

        def capture(backend, messages):
            observed.append(backend)
            return len(messages)

        with patch.object(SMTPBackend, "send_messages", capture):
            self.guest()
            self.assertEqual(process_mail(), 1)
        backend = observed[0]
        self.assertEqual(backend.host, "host.invalid")
        self.assertEqual(backend.port, 2526)
        self.assertEqual(backend.username, "host-user")
        self.assertEqual(backend.password, "synthetic-host-password")
        self.assertFalse(backend.use_tls)
        self.assertTrue(backend.use_ssl)
        self.assertEqual(backend.timeout, 4.5)

    @override_settings(
        COMMENTAIL_EMAIL={
            "BACKEND": "tests.test_independent_email.CustomSMTPBackend",
            "OPTIONS": {
                "host": "comments.invalid",
                "token": "synthetic-token",
                "timeout": 120,
            },
        }
    )
    def test_smtp_subclass_options_and_timeout_keep_standard_contract(self):
        observed = []

        def capture(backend, messages):
            observed.append(backend)
            return len(messages)

        with patch.object(CustomSMTPBackend, "send_messages", capture):
            self.assertEqual(check_settings(None), [])
            self.assertTrue(email_configured())
            self.guest()
            self.assertEqual(process_mail(), 1)
        self.assertEqual(observed[0].token, "synthetic-token")
        self.assertEqual(observed[0].timeout, 30)
        self.assertEqual(observed[0].host, "comments.invalid")

    @override_settings(COMMENTAIL_EMAIL={"BACKEND": BACKEND})
    def test_provider_constructor_failure_retries_without_host_fallback_or_secret(self):
        self.guest()
        with patch.object(
            ProviderBackend, "__init__", side_effect=ProviderError("private-secret")
        ):
            self.assertEqual(process_mail(), 0)
        job = MailJob.objects.get()
        deadline, token_id = job.expires_at, job.token_id
        self.assertEqual(job.status, "pending")
        self.assertEqual(job.error, "ProviderError")
        self.assertIsNone(job.lease_until)
        self.assertEqual(mail.outbox, [])

        MailJob.objects.filter(pk=job.pk).update(next_attempt_at=timezone.now())
        self.assertEqual(process_mail(), 1)
        job.refresh_from_db()
        self.assertEqual(job.status, "sent")
        self.assertEqual(job.expires_at, deadline)
        self.assertEqual(job.token_id, token_id)
        self.assertEqual(job.attempts, 2)

    @override_settings(COMMENTAIL_EMAIL={"BACKEND": BACKEND})
    def test_failed_independent_send_does_not_abort_other_jobs_or_fall_back(self):
        first, second = self.guest(), self.guest()
        first_job = MailJob.objects.get(comment=first)
        send = ProviderBackend.send_messages

        def fail_first(backend, messages):
            if (
                messages[0]
                .extra_headers["Message-ID"]
                .startswith(f"<commentail-{first_job.pk}@")
            ):
                raise ProviderError("private-secret")
            return send(backend, messages)

        with patch.object(ProviderBackend, "send_messages", fail_first):
            self.assertEqual(process_mail(), 1)
        first_job.refresh_from_db()
        self.assertEqual(first_job.status, "pending")
        self.assertEqual(first_job.error, "ProviderError")
        self.assertEqual(MailJob.objects.get(comment=second).status, "sent")
        self.assertEqual(mail.outbox, [])

    @override_settings(COMMENTAIL_EMAIL={"BACKEND": BACKEND})
    def test_existing_jobs_use_current_transport_and_sender(self):
        self.guest()
        with override_settings(
            COMMENTAIL_EMAIL={"FROM_EMAIL": "changed@example.invalid"}
        ):
            self.assertEqual(process_mail(), 1)
        self.assertEqual(ProviderBackend.messages, [])
        self.assertEqual(mail.outbox[0].from_email, "changed@example.invalid")

    def test_invalid_active_configuration_releases_jobs_and_recovers_after_correction(
        self,
    ):
        for configuration in (
            {"OPTIONS": {"api_key": "private-secret"}},
            {"FROM_EMAIL": "private-secret\nBcc: injected@example.invalid"},
            {"BACKEND": "missing.private-secret.Backend"},
        ):
            with self.subTest(configuration=configuration):
                first, second = self.guest(), self.guest()
                host_messages = len(mail.outbox)
                jobs = MailJob.objects.filter(comment__in=(first, second))
                deadlines = dict(jobs.values_list("pk", "expires_at"))
                with override_settings(COMMENTAIL_EMAIL=configuration):
                    self.assertEqual(process_mail(), 0)
                self.assertEqual(
                    jobs.filter(status="pending", lease_until=None).count(), 2
                )
                self.assertTrue(
                    all(job.error == "ImproperlyConfigured" for job in jobs)
                )
                self.assertEqual(len(mail.outbox), host_messages)
                jobs.update(next_attempt_at=timezone.now())
                self.assertEqual(process_mail(), 2)
                self.assertEqual(jobs.filter(status="sent", attempts=2).count(), 2)
                self.assertEqual(dict(jobs.values_list("pk", "expires_at")), deadlines)


@override_settings(COMMENTAIL_EMAIL={"BACKEND": BACKEND})
class IndependentEmailSchedulerTests(TransactionTestCase):
    def setUp(self):
        ProviderBackend.messages = []
        ProviderBackend.configurations = []
        Locale.objects.get_or_create(language_code="en")
        root = Page.get_first_root_node()
        if root is None:
            root = Page.add_root(title="Synthetic root", slug="root")
        site = Site.objects.create(hostname="independent-email.invalid", root_page=root)
        self.discussion = Discussion.objects.create(site=site, page=root)

    def test_host_task_and_command_share_independent_transport(self):
        for name in ("First", "Second"):
            submit(
                self.discussion.pk,
                text=name,
                guest_name=name,
                guest_email="guest@example.invalid",
            )
        self.assertEqual(process_pending(mail_limit=1), {"sent": 1, "removed": 0})
        call_command("process_commentail", stdout=StringIO())
        self.assertEqual(len(ProviderBackend.messages), 2)
        self.assertEqual(mail.outbox, [])
        self.assertEqual(process_pending(), {"sent": 0, "removed": 0})
        self.assertEqual(MailJob.objects.filter(status="sent").count(), 2)
