from datetime import timedelta

from django.contrib.sessions.backends.db import SessionStore
from django.test import RequestFactory, TestCase, override_settings
from django.utils import timezone
from wagtail.models import Site

from commentail.models import CaptchaChallenge, Discussion, GuestGrant
from commentail.security import (
    ArithmeticCaptcha,
    issue_token,
    remember_guest,
    remembered_guest,
    verify_token,
)
from commentail.services import DomainError


class SecurityTests(TestCase):
    def setUp(self):
        self.site = Site.objects.get(is_default_site=True)
        self.discussion = Discussion.objects.create(
            site=self.site, page=self.site.root_page
        )
        from commentail.services import submit

        self.comment = submit(
            self.discussion.pk,
            text="Guest",
            guest_name="Guest",
            guest_email="guest@example.invalid",
        )
        self.request = RequestFactory().get("/")
        self.request.session = SessionStore()
        self.request.session.create()

    def test_token_secret_not_stored_and_purpose_is_scoped(self):
        secret = issue_token(
            self.comment, "confirm", timezone.now() + timedelta(hours=1)
        )
        row = verify_token(secret, "confirm", self.site)
        self.assertNotEqual(row.digest, secret)
        self.assertEqual(
            verify_token(secret, "confirm", self.site).comment_id, self.comment.pk
        )
        with self.assertRaises(DomainError):
            verify_token(secret, "edit", self.site)
        second = Site.objects.create(
            hostname="other.invalid", root_page=self.site.root_page
        )
        with self.assertRaises(DomainError):
            verify_token(secret, "confirm", second)

    def test_expired_and_unknown_tokens_fail(self):
        secret = issue_token(
            self.comment, "edit", timezone.now() - timedelta(seconds=1)
        )
        with self.assertRaises(DomainError):
            verify_token(secret, "edit", self.site)
        with self.assertRaises(DomainError):
            verify_token("unknown", "edit", self.site)

    def test_remembered_email_has_fixed_site_scoped_expiry(self):
        secret = remember_guest(self.site, "guest@example.invalid")
        row = GuestGrant.objects.get()
        original = row.expires_at
        self.assertEqual(
            remembered_guest(secret, self.site).email, "guest@example.invalid"
        )
        row.refresh_from_db()
        self.assertEqual(row.expires_at, original)
        second = Site.objects.create(
            hostname="second.invalid", root_page=self.site.root_page
        )
        self.assertIsNone(remembered_guest(secret, second))
        GuestGrant.objects.update(expires_at=timezone.now())
        self.assertIsNone(remembered_guest(secret, self.site))

    def test_captcha_is_bound_and_one_use(self):
        backend = ArithmeticCaptcha()
        challenge = backend.create(self.request, self.site)
        row = CaptchaChallenge.objects.get(pk=challenge.id)
        other = RequestFactory().get("/")
        other.session = SessionStore()
        other.session.create()
        self.assertFalse(
            backend.verify(other, self.site, challenge.id, str(row.answer))
        )
        self.assertTrue(
            backend.verify(self.request, self.site, challenge.id, str(row.answer))
        )
        self.assertFalse(
            backend.verify(self.request, self.site, challenge.id, str(row.answer))
        )
        self.assertNotIn("answer", challenge.data)

    def test_captcha_refresh_and_five_wrong_attempts(self):
        backend = ArithmeticCaptcha()
        first = backend.create(self.request, self.site)
        second = backend.create(self.request, self.site)
        row = CaptchaChallenge.objects.get(pk=second.id)
        self.assertFalse(backend.verify(self.request, self.site, first.id, "1"))
        for _ in range(5):
            self.assertFalse(
                backend.verify(self.request, self.site, second.id, "wrong")
            )
        self.assertFalse(
            backend.verify(self.request, self.site, second.id, str(row.answer))
        )

    def test_expired_captcha_fails(self):
        backend = ArithmeticCaptcha()
        challenge = backend.create(self.request, self.site)
        row = CaptchaChallenge.objects.get(pk=challenge.id)
        CaptchaChallenge.objects.update(expires_at=timezone.now())
        self.assertFalse(
            backend.verify(self.request, self.site, challenge.id, str(row.answer))
        )


class ConfigurationTests(TestCase):
    def test_hostname_inherits_default(self):
        from commentail.config import technical_settings

        site = Site.objects.get(is_default_site=True)
        with override_settings(
            COMMENTAIL={
                "default": {"EDIT_WINDOW_SECONDS": 800},
                site.hostname: {"EMAIL_CONFIRM_SECONDS": 120},
            }
        ):
            values = technical_settings(site)
            self.assertEqual(values["EDIT_WINDOW_SECONDS"], 800)
            self.assertEqual(values["EMAIL_CONFIRM_SECONDS"], 120)

    def test_invalid_configuration_fails_explicitly(self):
        from commentail.config import configuration_errors

        for value in [
            [],
            {"default": {"TYPO": 1}},
            {"default": {"EDIT_WINDOW_SECONDS": True}},
            {"default": {"EDIT_WINDOW_SECONDS": 0}},
        ]:
            with self.subTest(value=value), override_settings(COMMENTAIL=value):
                self.assertTrue(configuration_errors())


class LogSafetyTests(TestCase):
    def test_encoded_capability_parameter_names_are_redacted(self):
        from commentail.logging import redact

        for key in ("%74oken", "to%6ben", "%74%6F%6b%65%6e"):
            with self.subTest(key=key):
                value = redact(f"GET /commentail/actions/edit/?{key}=private-secret&other=kept HTTP/1.1")
                self.assertNotIn("private-secret", value)
                self.assertIn("other=kept", value)
                self.assertIn("[redacted]", value)

    def test_capability_query_is_redacted_in_django_log(self):
        import logging

        from commentail.logging import CapabilityFilter

        record = logging.LogRecord(
            "django.server",
            20,
            "",
            1,
            '"%s" %s',
            ("GET /commentail/actions/edit/?token=private-secret HTTP/1.1", 200),
            None,
        )
        CapabilityFilter().filter(record)
        self.assertNotIn("private-secret", record.getMessage())
        self.assertIn("[redacted]", record.getMessage())
