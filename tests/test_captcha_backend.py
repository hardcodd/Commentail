import io
import json
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

    def test_refresh_during_provider_verification_cannot_authorize_old_task(self):
        task = create_captcha(self.request, self.site)

        def refresh(*args):
            create_captcha(self.request, self.site)
            return True

        with patch.object(CustomCaptcha, "verify", side_effect=refresh):
            self.assertFalse(verify_captcha(self.request, self.site, task.id, "ok"))

    def test_inflight_verification_cannot_be_used_concurrently(self):
        task = create_captcha(self.request, self.site)
        CaptchaChallenge.objects.filter(pk=task.id).update(verifying=True)
        self.assertFalse(verify_captcha(self.request, self.site, task.id, "ok"))
        self.assertEqual(CustomCaptcha.calls, [])

    def test_refresh_replaces_only_the_selected_independent_form(self):
        first = create_captcha(self.request, self.site, replace_id="")
        second = create_captcha(self.request, self.site, replace_id="")
        create_captcha(self.request, self.site, replace_id=first.id)
        self.assertFalse(verify_captcha(self.request, self.site, first.id, "ok"))
        self.assertTrue(verify_captcha(self.request, self.site, second.id, "ok"))

    def test_refresh_cannot_invalidate_another_sessions_task(self):
        task = create_captcha(self.request, self.site, replace_id="")
        other = RequestFactory().get("/", HTTP_USER_AGENT="Browser")
        other.session = SessionStore()
        other.session.create()
        create_captcha(other, self.site, replace_id=task.id)
        self.assertTrue(verify_captcha(self.request, self.site, task.id, "ok"))

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

    def test_bundled_providers_accept_fresh_proof_after_long_writing(self):
        from django.urls import reverse

        from commentail.models import Comment

        for backend, payload in (
            ("GoogleRecaptcha", {"success": True, "hostname": "testserver"}),
            ("YandexSmartCaptcha", {"status": "ok", "host": "testserver"}),
        ):
            with (
                self.subTest(backend=backend),
                override_settings(
                    COMMENTAIL={
                        "default": {
                            "CAPTCHA_BACKEND": "commentail.captcha_providers."
                            + backend,
                            "CAPTCHA_OPTIONS": {
                                "site_key": "public",
                                "secret_key": "private",
                            },
                        }
                    },
                    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
                ),
            ):
                response = self.client.get(
                    reverse("commentail:discussion", args=[self.site.root_page.pk])
                )
                challenge_id = response.context["captcha"].id
                later = timezone.now() + timedelta(minutes=20)
                data = {
                    "key": response.context["form_key"],
                    "challenge": challenge_id,
                    "answer": "fresh-provider-proof",
                    "text": "Long writing regression " + backend,
                    "name": "Guest",
                    "email": backend.lower() + "@example.invalid",
                }
                with (
                    patch("django.utils.timezone.now", return_value=later),
                    patch(
                        "commentail.captcha_providers.urlopen",
                        return_value=io.BytesIO(json.dumps(payload).encode()),
                    ) as remote,
                ):
                    CaptchaChallenge.objects.filter(expires_at__lte=later).delete()
                    result = self.client.post(
                        reverse("commentail:submit", args=[self.site.root_page.pk]),
                        data,
                    )
                self.assertEqual(result.status_code, 302)
                remote.assert_called_once()
                self.assertTrue(CaptchaChallenge.objects.get(pk=challenge_id).used)
                self.assertEqual(
                    Comment.objects.get(email=data["email"]).status, "awaiting_email"
                )
                submitted = RequestFactory().post("/")
                submitted.session = self.client.session
                with patch("commentail.captcha_providers.urlopen") as remote:
                    self.assertFalse(
                        verify_captcha(
                            submitted,
                            self.site,
                            challenge_id,
                            "fresh-provider-proof",
                        )
                    )
                remote.assert_not_called()

    def test_bundled_provider_binding_expires_with_form_and_rejects_bad_proofs(self):
        for backend, payload in (
            ("GoogleRecaptcha", {"success": False, "hostname": "testserver"}),
            ("YandexSmartCaptcha", {"status": "failed", "host": "testserver"}),
        ):
            with (
                self.subTest(backend=backend),
                override_settings(
                    COMMENTAIL={
                        "default": {
                            "CAPTCHA_BACKEND": "commentail.captcha_providers."
                            + backend,
                            "CAPTCHA_OPTIONS": {
                                "site_key": "public",
                                "secret_key": "private",
                            },
                            "FORM_TICKET_SECONDS": 1800,
                        }
                    },
                ),
            ):
                task = create_captcha(self.request, self.site)
                challenge = CaptchaChallenge.objects.get(pk=task.id)
                self.assertAlmostEqual(
                    (challenge.expires_at - timezone.now()).total_seconds(),
                    1800,
                    delta=2,
                )
                with (
                    patch(
                        "django.utils.timezone.now",
                        return_value=timezone.now() + timedelta(minutes=20),
                    ),
                    patch(
                        "commentail.captcha_providers.urlopen",
                        return_value=io.BytesIO(json.dumps(payload).encode()),
                    ) as remote,
                ):
                    self.assertFalse(
                        verify_captcha(
                            self.request, self.site, task.id, "invalid-proof"
                        )
                    )
                remote.assert_called_once()
                with (
                    patch(
                        "django.utils.timezone.now", return_value=challenge.expires_at
                    ),
                    patch("commentail.captcha_providers.urlopen") as remote,
                ):
                    self.assertFalse(
                        verify_captcha(self.request, self.site, task.id, "proof")
                    )
                remote.assert_not_called()

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
