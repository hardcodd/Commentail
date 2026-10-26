"""Exercise test delivery without creating comments or processing the outbox."""

from io import StringIO
from unittest.mock import patch

from django.conf import settings
from django.core import mail
from django.core.mail.backends.smtp import EmailBackend as SMTPBackend
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings

from tests.test_independent_email import BACKEND, ProviderBackend, ProviderError
from tests.test_smtp_chain import smtp_receiver


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="site@example.invalid",
)
class TestEmailCommandTests(SimpleTestCase):
    def setUp(self):
        ProviderBackend.messages = []
        ProviderBackend.configurations = []

    def send(self):
        output = StringIO()
        call_command(
            "test_commentail_email", to="recipient@example.invalid", stdout=output
        )
        return output.getvalue()

    @override_settings(COMMENTAIL_EMAIL={})
    def test_shared_settings_send_one_message_without_database_access(self):
        result = self.send()
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["recipient@example.invalid"])
        self.assertEqual(mail.outbox[0].from_email, "site@example.invalid")
        self.assertIn("backend accepted", result)
        self.assertIn("does not confirm inbox delivery", result)

    @override_settings(
        COMMENTAIL_EMAIL={
            "BACKEND": BACKEND,
            "OPTIONS": {"api_key": "private-secret"},
            "FROM_EMAIL": "comments@example.invalid",
        }
    )
    def test_separate_transport_and_sender(self):
        result = self.send()
        self.assertEqual(len(ProviderBackend.messages), 1)
        self.assertEqual(
            ProviderBackend.messages[0].from_email, "comments@example.invalid"
        )
        self.assertEqual(
            ProviderBackend.configurations, [("private-secret", 12, False)]
        )
        self.assertEqual(mail.outbox, [])
        self.assertNotIn("private-secret", result)

    def test_invalid_or_multiple_recipients_never_construct_transport(self):
        with patch(
            "commentail.management.commands.test_commentail_email.connection"
        ) as connect:
            for recipient in (
                "",
                "not-an-address",
                "a@example.org,b@example.org",
                "a@example.org\nBcc: b@example.org",
            ):
                with self.subTest(recipient=recipient), self.assertRaises(CommandError):
                    call_command(
                        "test_commentail_email", to=recipient, stdout=StringIO()
                    )
            connect.assert_not_called()

    @override_settings(COMMENTAIL_EMAIL={"BACKEND": BACKEND})
    def test_transport_failure_is_redacted_and_does_not_fall_back(self):
        with (
            patch.object(
                ProviderBackend,
                "send_messages",
                side_effect=ProviderError("private-secret"),
            ),
            self.assertRaises(CommandError) as failure,
        ):
            self.send()
        self.assertIn("ProviderError", str(failure.exception))
        self.assertNotIn("private-secret", str(failure.exception))
        self.assertEqual(mail.outbox, [])

    @override_settings(COMMENTAIL_EMAIL={"BACKEND": BACKEND})
    def test_zero_acceptance_is_an_error(self):
        with (
            patch.object(ProviderBackend, "send_messages", return_value=0),
            self.assertRaisesMessage(CommandError, "did not accept"),
        ):
            self.send()

    def test_real_local_smtp_receives_command_message_without_database_access(self):
        with (
            smtp_receiver() as received,
            override_settings(
                EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
                COMMENTAIL_EMAIL={
                    "BACKEND": "django.core.mail.backends.smtp.EmailBackend",
                    "OPTIONS": {
                        "host": "127.0.0.1",
                        "port": settings.EMAIL_PORT,
                        "timeout": 3,
                    },
                    "FROM_EMAIL": "comments@example.invalid",
                },
            ),
        ):
            self.assertIn("backend accepted", self.send())
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]["From"], "comments@example.invalid")
        self.assertEqual(received[0]["To"], "recipient@example.invalid")
        self.assertEqual(mail.outbox, [])

    @override_settings(COMMENTAIL_EMAIL={"OPTIONS": {"api_key": "private-secret"}})
    def test_invalid_configuration_is_redacted(self):
        with self.assertRaises(CommandError) as failure:
            self.send()
        self.assertNotIn("private-secret", str(failure.exception))

    def test_smtp_timeout_is_bounded_before_open_and_connection_is_closed(self):
        for timeout, expected in ((None, 30), (120, 30), (3, 3)):
            observed = []

            def opened(backend, observed=observed):
                observed.append(backend.timeout)

            with (
                self.subTest(timeout=timeout),
                override_settings(
                    COMMENTAIL_EMAIL={
                        "BACKEND": "django.core.mail.backends.smtp.EmailBackend",
                        "OPTIONS": {"host": "synthetic.invalid", "timeout": timeout},
                    }
                ),
                patch.object(SMTPBackend, "open", opened),
                patch.object(SMTPBackend, "send_messages", return_value=1),
                patch.object(SMTPBackend, "close") as close,
            ):
                self.send()
                self.assertEqual(observed, [expected])
                close.assert_called_once()
