from datetime import timedelta
from typing import ClassVar
from unittest.mock import patch

from django.contrib.sessions.backends.db import SessionStore
from django.test import RequestFactory, TestCase, override_settings
from django.utils import timezone
from wagtail.models import Site

from commentail.config import configuration_errors
from commentail.models import CaptchaChallenge
from commentail.security import CaptchaTask, create_captcha, verify_captcha
from commentail.services import DomainError


class CustomCaptcha:
    calls: ClassVar[list[str]] = []

    def create(self, request, site):
        return CaptchaTask(
            "provider-key", "commentail/captcha.html", {"question": "Test task"}
        )

    def verify(self, request, site, challenge_id, answer):
        self.calls.append(challenge_id)
        return answer == "ok"


@override_settings(
    COMMENTAIL={
        "default": {"CAPTCHA_BACKEND": "tests.test_captcha_backend.CustomCaptcha"}
    }
)
class CaptchaBackendTests(TestCase):
    def setUp(self):
        self.site = Site.objects.get(is_default_site=True)
        self.request = RequestFactory().get("/", HTTP_USER_AGENT="Synthetic browser")
        self.request.session = SessionStore()
        self.request.session.create()
        CustomCaptcha.calls = []

    def test_custom_task_is_wrapped_and_verified_once(self):
        task = create_captcha(self.request, self.site)
        self.assertNotEqual(str(task.id), "provider-key")
        self.assertEqual(task.data["question"], "Test task")
        self.assertTrue(verify_captcha(self.request, self.site, task.id, "ok"))
        self.assertEqual(CustomCaptcha.calls, ["provider-key"])
        self.assertFalse(verify_captcha(self.request, self.site, task.id, "ok"))

    def test_wrong_session_site_and_expiry_do_not_call_backend(self):
        task = create_captcha(self.request, self.site)
        other = RequestFactory().get("/")
        other.session = SessionStore()
        other.session.create()
        second = Site.objects.create(
            hostname="second.invalid", root_page=self.site.root_page
        )
        self.assertFalse(verify_captcha(other, self.site, task.id, "ok"))
        self.assertFalse(verify_captcha(self.request, second, task.id, "ok"))
        CaptchaChallenge.objects.filter(pk=task.id).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        self.assertFalse(verify_captcha(self.request, self.site, task.id, "ok"))
        self.assertEqual(CustomCaptcha.calls, [])

    def test_attempt_limit_refresh_and_backend_change(self):
        old = create_captcha(self.request, self.site)
        task = create_captcha(self.request, self.site)
        self.assertFalse(verify_captcha(self.request, self.site, old.id, "ok"))
        for _ in range(5):
            self.assertFalse(verify_captcha(self.request, self.site, task.id, "bad"))
        self.assertFalse(verify_captcha(self.request, self.site, task.id, "ok"))
        self.assertEqual(len(CustomCaptcha.calls), 5)
        task = create_captcha(self.request, self.site)
        with override_settings(COMMENTAIL={}):
            self.assertFalse(verify_captcha(self.request, self.site, task.id, "ok"))

    def test_provider_failures_deny_and_count_attempt(self):
        task = create_captcha(self.request, self.site)
        with (
            patch.object(
                CustomCaptcha,
                "verify",
                side_effect=RuntimeError("Synthetic provider failure"),
            ),
            self.assertLogs("commentail.captcha", level="ERROR"),
        ):
            self.assertFalse(verify_captcha(self.request, self.site, task.id, "ok"))
        self.assertEqual(CaptchaChallenge.objects.get(pk=task.id).attempts, 1)
        with (
            patch.object(
                CustomCaptcha,
                "create",
                side_effect=RuntimeError("Synthetic provider failure"),
            ),
            self.assertLogs("commentail.captcha", level="ERROR"),
            self.assertRaises(DomainError),
        ):
            create_captcha(self.request, self.site)

    def test_fifth_attempt_can_succeed_and_is_consumed(self):
        task = create_captcha(self.request, self.site)
        for _ in range(4):
            self.assertFalse(verify_captcha(self.request, self.site, task.id, "bad"))
        self.assertTrue(verify_captcha(self.request, self.site, task.id, "ok"))
        self.assertTrue(CaptchaChallenge.objects.get(pk=task.id).used)
        self.assertFalse(verify_captcha(self.request, self.site, task.id, "ok"))

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
        EMAIL_HOST="smtp.invalid",
    )
    def test_custom_backend_is_used_by_public_form_and_admission(self):
        from django.urls import reverse

        response = self.client.get(
            reverse("commentail:discussion", args=[self.site.root_page.pk])
        )
        self.assertContains(response, "Test task")
        response = self.client.post(
            reverse("commentail:submit", args=[self.site.root_page.pk]),
            {
                "key": response.context["form_key"],
                "challenge": response.context["captcha"].id,
                "answer": "ok",
                "text": "Synthetic custom guest",
                "name": "Guest",
                "email": "synthetic@example.invalid",
            },
        )
        self.assertEqual(response.status_code, 302)
        from commentail.models import Comment

        self.assertEqual(Comment.objects.get().status, "awaiting_email")

    def test_bad_contract_and_config_fail_closed(self):
        with (
            patch.object(CustomCaptcha, "create", return_value="bad"),
            self.assertLogs("commentail.captcha", level="ERROR"),
            self.assertRaises(DomainError),
        ):
            create_captcha(self.request, self.site)
        with override_settings(
            COMMENTAIL={"default": {"CAPTCHA_BACKEND": "builtins.str"}}
        ):
            self.assertTrue(configuration_errors())
        self.assertFalse(configuration_errors())
