from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.contrib.sessions.backends.db import SessionStore
from django.test import RequestFactory, TestCase, override_settings
from wagtail.models import PageViewRestriction, Site

from commentail.admission import accept_request, issue_form
from commentail.models import CaptchaChallenge, Comment, Discussion
from commentail.security import ArithmeticCaptcha, remember_guest
from commentail.services import DomainError


class AdmissionTests(TestCase):
    def setUp(self):
        self.site = Site.objects.get(is_default_site=True)
        self.discussion = Discussion.objects.create(
            site=self.site, page=self.site.root_page
        )
        self.user = get_user_model().objects.create_user("writer")
        self.request = RequestFactory().post(
            "/", REMOTE_ADDR="127.0.0.1", HTTP_USER_AGENT="Synthetic browser"
        )
        self.request.user = self.user
        self.request.session = SessionStore()
        self.request.session.create()
        self.key = issue_form(self.request, self.discussion)

    def test_registered_post_and_idempotent_retry(self):
        first = accept_request(
            self.request, self.discussion.pk, self.key, text="Message"
        )
        second = accept_request(
            self.request, self.discussion.pk, self.key, text="Message"
        )
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(Comment.objects.count(), 1)

    def test_session_binding(self):
        self.request.session = SessionStore()
        self.request.session.create()
        with self.assertRaises(DomainError):
            accept_request(self.request, self.discussion.pk, self.key, text="Message")

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend", EMAIL_HOST=""
    )
    def test_unconfigured_delivery_blocks_guest_before_creation(self):
        self.request.user = AnonymousUser()
        with self.assertRaisesMessage(
            DomainError, "Guest comments require configured email delivery"
        ):
            accept_request(
                self.request,
                self.discussion.pk,
                self.key,
                text="Guest",
                guest_name="Guest",
                guest_email="guest@example.invalid",
            )
        self.assertFalse(Comment.objects.exists())

    def test_private_page_is_not_bypassed_by_replay(self):
        accept_request(self.request, self.discussion.pk, self.key, text="Message")
        PageViewRestriction.objects.create(
            page=self.site.root_page, restriction_type="groups"
        )
        with self.assertRaises(DomainError):
            accept_request(self.request, self.discussion.pk, self.key, text="Message")

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
        EMAIL_HOST="smtp.invalid",
    )
    def test_guest_captcha_and_mail_proof(self):
        self.request.user = AnonymousUser()
        challenge = ArithmeticCaptcha().create(self.request, self.site)
        answer = str(CaptchaChallenge.objects.get(pk=challenge.id).answer)
        comment = accept_request(
            self.request,
            self.discussion.pk,
            self.key,
            text="Guest",
            guest_name="Guest",
            guest_email="guest@example.invalid",
            challenge_id=str(challenge.id),
            answer=answer,
        )
        self.assertEqual(comment.status, "awaiting_email")
        duplicate = accept_request(
            self.request,
            self.discussion.pk,
            self.key,
            text="Guest",
            guest_name="Guest",
            guest_email="guest@example.invalid",
            challenge_id=str(challenge.id),
            answer=answer,
        )
        self.assertEqual(comment.pk, duplicate.pk)

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
        EMAIL_HOST="smtp.invalid",
    )
    def test_wrong_captcha_attempt_is_not_rolled_back(self):
        self.request.user = AnonymousUser()
        challenge = ArithmeticCaptcha().create(self.request, self.site)
        with self.assertRaises(DomainError):
            accept_request(
                self.request,
                self.discussion.pk,
                self.key,
                text="Guest",
                guest_name="Guest",
                guest_email="guest@example.invalid",
                challenge_id=str(challenge.id),
                answer="wrong",
            )
        self.assertEqual(CaptchaChallenge.objects.get(pk=challenge.id).attempts, 1)
        self.assertFalse(Comment.objects.exists())

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
        EMAIL_HOST="smtp.invalid",
    )
    def test_remembered_email_skips_captcha_and_confirmation(self):
        self.request.user = AnonymousUser()
        secret = remember_guest(self.site, "guest@example.invalid")
        self.request.COOKIES[f"commentail_guest_{self.site.pk}"] = secret
        comment = accept_request(
            self.request,
            self.discussion.pk,
            self.key,
            text="Guest",
            guest_name="Guest",
            guest_email="guest@example.invalid",
        )
        self.assertEqual(comment.status, "pending")
        self.assertIsNotNone(comment.email_confirmed_at)

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
        EMAIL_HOST="smtp.invalid",
    )
    def test_remembered_email_does_not_prove_different_address(self):
        self.request.user = AnonymousUser()
        self.request.COOKIES[f"commentail_guest_{self.site.pk}"] = remember_guest(
            self.site, "guest@example.invalid"
        )
        with self.assertRaises(DomainError):
            accept_request(
                self.request,
                self.discussion.pk,
                self.key,
                text="Guest",
                guest_name="Guest",
                guest_email="other@example.invalid",
            )

    def test_author_quota_applies_to_new_form_keys(self):
        accept_request(self.request, self.discussion.pk, self.key, text="First")
        other = issue_form(self.request, self.discussion)
        with self.assertRaises(DomainError):
            accept_request(self.request, self.discussion.pk, other, text="Second")
        self.assertEqual(Comment.objects.count(), 1)
