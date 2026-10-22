from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser
from django.contrib.sessions.backends.db import SessionStore
from django.test import RequestFactory, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from wagtail.models import Site

from commentail.admission import accept_request, issue_form
from commentail.models import CaptchaChallenge, Comment, Discussion, FormTicket
from commentail.security import ArithmeticCaptcha, remember_guest
from commentail.services import DomainError


class GuestAntispamTests(TestCase):
    def setUp(self):
        self.site = Site.objects.get(is_default_site=True)
        self.discussion = Discussion.objects.create(
            site=self.site, page=self.site.root_page
        )
        self.request = RequestFactory().post(
            "/", REMOTE_ADDR="127.0.0.1", HTTP_USER_AGENT="Browser"
        )
        self.request.user = AnonymousUser()
        self.request.session = SessionStore()
        self.request.session.create()
        self.request.COOKIES[f"commentail_guest_{self.site.pk}"] = remember_guest(
            self.site, "guest@example.invalid"
        )

    def send(self, **kwargs):
        key = kwargs.pop("key", None) or issue_form(self.request, self.discussion)
        return accept_request(
            self.request,
            self.discussion.pk,
            key,
            text="A comment",
            guest_name="Guest",
            guest_email="guest@example.invalid",
            **kwargs,
        )

    def test_honeypot_is_reviewed_not_discarded(self):
        comment = self.send(honeypot="autofilled")
        self.assertEqual(comment.status, "pending")
        self.assertTrue(comment.suspicious)
        self.assertIn("honeypot", comment.spam_signals)

    def test_fast_form_is_only_a_moderation_signal(self):
        comment = self.send()
        self.assertIn("fast_form", comment.spam_signals)
        self.assertIsNotNone(comment.email_confirmed_at)

    def test_ordinary_remembered_guest_has_no_extra_challenge(self):
        key = issue_form(self.request, self.discussion)
        FormTicket.objects.filter(discussion=self.discussion).update(
            issued_at=timezone.now() - timedelta(seconds=10)
        )
        comment = self.send(key=key)
        self.assertFalse(comment.suspicious)

    def test_independent_tabs_do_not_invalidate_each_others_proofs(self):
        from commentail.security import verify_captcha

        url = reverse("commentail:discussion", args=[self.site.root_page.pk])
        first = self.client.get(url, HTTP_USER_AGENT="Browser")
        second = self.client.get(url, HTTP_USER_AGENT="Browser")
        first_task = first.context["captcha"]
        second_task = second.context["captcha"]
        refreshed = self.client.post(
            reverse("commentail:submit", args=[self.site.root_page.pk]),
            {
                "key": first.context["form_key"],
                "challenge": first_task.id,
                "refresh": "1",
            },
            HTTP_USER_AGENT="Browser",
        )
        request = refreshed.wsgi_request
        first_row = CaptchaChallenge.objects.get(pk=first_task.id)
        self.assertTrue(first_row.used)
        self.assertFalse(
            verify_captcha(request, self.site, first_task.id, str(first_row.answer))
        )
        answer = str(CaptchaChallenge.objects.get(pk=second_task.id).answer)
        self.assertTrue(verify_captcha(request, self.site, second_task.id, answer))
        self.assertFalse(verify_captcha(request, self.site, second_task.id, answer))

    def test_refresh_retains_server_owned_form_age(self):
        from commentail.security import digest

        url = reverse("commentail:discussion", args=[self.site.root_page.pk])
        form = self.client.get(url, HTTP_USER_AGENT="Browser")
        started = timezone.now() - timedelta(seconds=20)
        FormTicket.objects.filter(digest=digest(form.context["form_key"])).update(
            issued_at=started
        )
        refreshed = self.client.post(
            reverse("commentail:submit", args=[self.site.root_page.pk]),
            {
                "key": form.context["form_key"],
                "refresh": "1",
                "issued_at": "2000-01-01",
            },
            HTTP_USER_AGENT="Browser",
        )
        ticket = FormTicket.objects.get(digest=digest(refreshed.context["form_key"]))
        self.assertEqual(ticket.issued_at, started)

    def test_form_age_cannot_be_borrowed_from_another_browser(self):
        from commentail.security import digest

        key = issue_form(self.request, self.discussion)
        started = timezone.now() - timedelta(seconds=20)
        FormTicket.objects.filter(digest=digest(key)).update(issued_at=started)
        fresh = self.client.post(
            reverse("commentail:submit", args=[self.site.root_page.pk]),
            {"key": key, "refresh": "1"},
            HTTP_USER_AGENT="Browser",
        )
        ticket = FormTicket.objects.get(digest=digest(fresh.context["form_key"]))
        self.assertGreater(ticket.issued_at, started)

    def test_navigation_age_ids_are_bound_and_consumed_forms_cannot_age_new_comments(
        self,
    ):
        from commentail.security import digest
        from commentail.widget import block_context

        key = issue_form(self.request, self.discussion)
        ticket = FormTicket.objects.get(digest=digest(key))
        started = timezone.now() - timedelta(seconds=20)
        FormTicket.objects.filter(pk=ticket.pk).update(issued_at=started)
        self.request.method = "GET"
        self.request.GET = self.request.GET.copy()
        self.request.GET["form_age"] = str(ticket.pk)
        context = block_context(self.request, self.discussion)
        self.assertEqual(
            FormTicket.objects.get(digest=digest(context["form_key"])).issued_at,
            started,
        )
        self.send(key=key)
        context = block_context(self.request, self.discussion)
        self.assertGreater(
            FormTicket.objects.get(digest=digest(context["form_key"])).issued_at,
            started,
        )

    def test_document_draft_recovery_retains_age_without_replaying_proof(self):
        from commentail.drafts import load_draft, save_draft
        from commentail.security import digest
        from commentail.widget import block_context

        key = issue_form(self.request, self.discussion)
        started = timezone.now() - timedelta(seconds=20)
        FormTicket.objects.filter(digest=digest(key)).update(issued_at=started)
        self.request.POST = self.request.POST.copy()
        self.request.POST.update(
            {"key": key, "text": "Keep this draft", "answer": "private-proof"}
        )
        destination = save_draft(self.request, self.discussion)
        from urllib.parse import parse_qs, urlsplit

        self.request.method = "GET"
        self.request.GET = self.request.GET.copy()
        self.request.GET.update(
            {k: v[0] for k, v in parse_qs(urlsplit(destination).query).items()}
        )
        values, _ = load_draft(self.request, self.discussion)
        self.assertNotIn("answer", values)
        context = block_context(self.request, self.discussion)
        ticket = FormTicket.objects.get(digest=digest(context["form_key"]))
        self.assertEqual(ticket.issued_at, started)

    @override_settings(COMMENTAIL={"default": {"GUEST_CAPTCHA_MODE": "always"}})
    def test_strict_mode_checks_remembered_guest(self):
        with self.assertRaisesMessage(DomainError, "CAPTCHA"):
            self.send()
        challenge = ArithmeticCaptcha().create(self.request, self.site)
        answer = str(CaptchaChallenge.objects.get(pk=challenge.id).answer)
        comment = self.send(challenge_id=str(challenge.id), answer=answer)
        self.assertIsNotNone(comment.email_confirmed_at)

    def test_suspicious_headers_require_captcha_even_with_email_proof(self):
        self.request.META["HTTP_SEC_FETCH_SITE"] = "cross-site"
        with self.assertRaisesMessage(DomainError, "CAPTCHA"):
            self.send()
        self.assertFalse(Comment.objects.exists())

    @override_settings(COMMENTAIL={"default": {"GUEST_ATTEMPTS_PER_MINUTE": 2}})
    def test_failed_proofs_spend_attempt_quota_before_provider_work(self):
        self.request.COOKIES.clear()
        for _ in range(2):
            with self.assertRaisesMessage(DomainError, "CAPTCHA"):
                self.send()
        with patch("commentail.admission.verify_captcha") as verify:
            with self.assertRaisesMessage(DomainError, "Too many attempts"):
                self.send()
            verify.assert_not_called()

    @override_settings(COMMENTAIL={"default": {"GUEST_IP_ATTEMPTS_PER_MINUTE": 1}})
    def test_new_sessions_and_emails_do_not_reset_the_ip_attempt_budget(self):
        self.request.COOKIES.clear()
        with self.assertRaisesMessage(DomainError, "CAPTCHA"):
            self.send()
        self.request.session = SessionStore()
        self.request.session.create()
        with patch("commentail.admission.verify_captcha") as verify:
            with self.assertRaisesMessage(DomainError, "Too many attempts"):
                accept_request(
                    self.request,
                    self.discussion.pk,
                    issue_form(self.request, self.discussion),
                    text="Message",
                    guest_name="Other",
                    guest_email="another@example.invalid",
                )
            verify.assert_not_called()

    @override_settings(COMMENTAIL={"default": {"GUEST_ATTEMPTS_PER_MINUTE": 1}})
    def test_accepted_retry_remains_idempotent_at_attempt_limit(self):
        key = issue_form(self.request, self.discussion)
        comment = self.send(key=key)
        self.assertEqual(self.send(key=key).pk, comment.pk)

    def test_public_honeypot_is_hidden_and_reaches_moderation(self):
        url = reverse("commentail:discussion", args=[self.site.root_page.pk])
        form = self.client.get(url, HTTP_USER_AGENT="Browser")
        self.assertContains(form, 'hidden aria-hidden="true"')
        challenge = form.context["captcha"]
        response = self.client.post(
            reverse("commentail:submit", args=[self.site.root_page.pk]),
            {
                "key": form.context["form_key"],
                "challenge": challenge.id,
                "answer": str(CaptchaChallenge.objects.get(pk=challenge.id).answer),
                "text": "A real comment",
                "name": "Guest",
                "email": "guest@example.invalid",
                "commentail_contact": "filled",
            },
            HTTP_USER_AGENT="Browser",
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("honeypot", Comment.objects.get().spam_signals)

    def test_issuance_failure_keeps_form_and_draft_editable(self):
        with patch(
            "commentail.widget.create_captcha",
            side_effect=DomainError("Captcha limit exceeded"),
        ):
            response = self.client.post(
                reverse("commentail:submit", args=[self.site.root_page.pk]),
                {
                    "text": "Keep my draft",
                    "name": "Guest",
                    "email": "guest@example.invalid",
                },
                HTTP_USER_AGENT="Browser",
            )
        self.assertContains(response, "Keep my draft", status_code=400)
        self.assertContains(response, 'name="refresh"', status_code=400)
        self.assertContains(response, 'name="text"', status_code=400)

    @override_settings(
        COMMENTAIL={
            "default": {
                "CAPTCHA_BACKEND": "commentail.captcha_providers.GoogleRecaptcha",
                "CAPTCHA_OPTIONS": {
                    "site_key": "synthetic-public",
                    "secret_key": "synthetic-secret",
                },
            }
        }
    )
    def test_external_failure_retains_draft_and_does_not_send_mail(self):
        from commentail.captcha_providers import ProviderUnavailable
        from commentail.models import MailJob

        form = self.client.get(
            reverse("commentail:discussion", args=[self.site.root_page.pk]),
            HTTP_USER_AGENT="Browser",
        )
        self.assertContains(form, 'data-commentail-provider="google"')
        self.assertNotContains(form, "synthetic-secret")
        self.assertContains(form, "requires JavaScript")
        with (
            patch(
                "commentail.captcha_providers.GoogleRecaptcha.verify",
                side_effect=ProviderUnavailable(),
            ),
            self.assertLogs("commentail.captcha", level="ERROR") as logs,
        ):
            response = self.client.post(
                reverse("commentail:submit", args=[self.site.root_page.pk]),
                {
                    "key": form.context["form_key"],
                    "challenge": form.context["captcha"].id,
                    "answer": "synthetic-token",
                    "text": "Keep this external draft",
                    "name": "Guest",
                    "email": "guest@example.invalid",
                },
                HTTP_USER_AGENT="Browser",
            )
        self.assertContains(response, "Keep this external draft", status_code=400)
        self.assertContains(response, "CAPTCHA is unavailable", status_code=400)
        self.assertFalse(MailJob.objects.exists())
        self.assertFalse(Comment.objects.exists())
        self.assertNotIn("synthetic-token", str(logs.output))
        self.assertNotIn("guest@example.invalid", str(logs.output))

    def test_external_no_javascript_has_explanation_and_no_fallback(self):
        from commentail.models import MailJob

        explanation = (
            "This site's spam check requires JavaScript. Enable JavaScript in "
            "your browser, complete the check, then send your comment."
        )
        for provider in ("GoogleRecaptcha", "YandexSmartCaptcha"):
            backend = f"commentail.captcha_providers.{provider}"
            with (
                self.subTest(provider=provider),
                override_settings(
                    COMMENTAIL={
                        "default": {
                            "CAPTCHA_BACKEND": backend,
                            "CAPTCHA_OPTIONS": {
                                "site_key": "synthetic-public",
                                "secret_key": "synthetic-secret",
                            },
                        }
                    }
                ),
                patch("commentail.captcha_providers.urlopen") as remote,
            ):
                form = self.client.get(
                    reverse("commentail:discussion", args=[self.site.root_page.pk]),
                    HTTP_USER_AGENT="Browser",
                )
                self.assertContains(form, f"<noscript><p>{explanation}</p></noscript>")
                self.assertContains(form, "data-commentail-provider-retry hidden")
                self.assertNotContains(form, ">Refresh task</button>")
                response = self.client.post(
                    reverse("commentail:submit", args=[self.site.root_page.pk]),
                    {
                        "key": form.context["form_key"],
                        "challenge": form.context["captcha"].id,
                        "answer": "",
                        "text": "Keep my no-JavaScript draft",
                        "name": "Guest",
                        "email": "guest@example.invalid",
                    },
                    HTTP_ACCEPT="text/html",
                    HTTP_USER_AGENT="Browser",
                )
                self.assertEqual(response.status_code, 303)
                recovered = self.client.get(
                    response["Location"], HTTP_USER_AGENT="Browser"
                )
                self.assertContains(recovered, explanation)
                self.assertContains(recovered, "Keep my no-JavaScript draft")
                task = CaptchaChallenge.objects.get(pk=recovered.context["captcha"].id)
                self.assertEqual(task.backend, backend)
                self.assertFalse(Comment.objects.exists())
                self.assertFalse(MailJob.objects.exists())
                remote.assert_not_called()

    def test_new_settings_fail_clearly_without_echoing_credentials(self):
        from commentail.config import configuration_errors

        for values in (
            {"CAPTCHA_OPTIONS": {"timeout": True}},
            {"CAPTCHA_OPTIONS": {"secret_key": "private", "unknown": "bad"}},
            {"GUEST_FORM_MIN_SECONDS": -1},
            {"GUEST_CAPTCHA_MODE": "off"},
            {"CAPTCHA_BACKEND": "commentail.captcha_providers.GoogleRecaptcha"},
        ):
            with (
                self.subTest(values=values),
                override_settings(COMMENTAIL={"default": values}),
            ):
                errors = configuration_errors()
                self.assertTrue(errors)
                self.assertNotIn("private", str(errors))


@override_settings(
    COMMENTAIL={
        "default": {"CAPTCHA_BACKEND": "tests.test_captcha_backend.CustomCaptcha"}
    }
)
class ExternalVerificationTransactionTests(TransactionTestCase):
    def setUp(self):
        from wagtail.models import Locale, Page

        Locale.objects.get_or_create(language_code="en")
        page = Page.get_first_root_node() or Page.add_root(title="Root", slug="root")
        self.site = Site.objects.filter(
            is_default_site=True
        ).first() or Site.objects.create(
            hostname="testserver", root_page=page, is_default_site=True
        )
        self.discussion = Discussion.objects.create(
            site=self.site, page=self.site.root_page
        )
        self.request = RequestFactory().post("/", HTTP_USER_AGENT="Browser")
        self.request.user = AnonymousUser()
        self.request.session = SessionStore()
        self.request.session.create()

    def send(self, verify):
        from commentail.security import create_captcha

        key = issue_form(self.request, self.discussion)
        task = create_captcha(self.request, self.site)
        with patch(
            "tests.test_captcha_backend.CustomCaptcha.verify", side_effect=verify
        ):
            return accept_request(
                self.request,
                self.discussion.pk,
                key,
                text="Message",
                guest_name="Guest",
                guest_email="guest@example.invalid",
                challenge_id=str(task.id),
                answer="proof",
            )

    def test_provider_work_runs_without_a_database_transaction(self):
        from django.db import connection

        def verify(*args):
            self.assertFalse(connection.in_atomic_block)
            return True

        self.assertEqual(self.send(verify).status, "awaiting_email")

    def test_access_is_rechecked_after_remote_work(self):
        from wagtail.models import PageViewRestriction

        def verify(*args):
            PageViewRestriction.objects.create(
                page=self.site.root_page, restriction_type="groups"
            )
            return True

        with self.assertRaisesMessage(DomainError, "Page access is required"):
            self.send(verify)
        self.assertFalse(Comment.objects.exists())

    def test_atomic_requests_does_not_wrap_proof_or_rollback_failed_attempts(self):
        from django.db import connection

        from commentail.models import RateEvent

        form = self.client.get(
            reverse("commentail:discussion", args=[self.site.root_page.pk]),
            HTTP_USER_AGENT="Browser",
        )

        def refuse(*args):
            self.assertFalse(connection.in_atomic_block)
            return False

        with (
            patch.dict(connection.settings_dict, ATOMIC_REQUESTS=True),
            patch(
                "tests.test_captcha_backend.CustomCaptcha.verify", side_effect=refuse
            ),
        ):
            response = self.client.post(
                reverse("commentail:submit", args=[self.site.root_page.pk]),
                {
                    "key": form.context["form_key"],
                    "challenge": form.context["captcha"].id,
                    "answer": "invalid",
                    "text": "Keep this draft",
                    "name": "Guest",
                    "email": "guest@example.invalid",
                },
                HTTP_USER_AGENT="Browser",
            )

        self.assertContains(response, "Keep this draft", status_code=400)
        self.assertEqual(RateEvent.objects.filter(kind="attempt_session").count(), 1)
        self.assertFalse(Comment.objects.exists())
