"""Reading/refresh cannot create unlimited form tickets after CAPTCHA throttling."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from wagtail.models import Site

from commentail.models import CaptchaChallenge, Comment, FormTicket, RateEvent


@override_settings(COMMENTAIL={"default": {"FORM_IP_LIMIT_PER_MINUTE": 2}})
class FormIssuanceLimitTests(TestCase):
    def setUp(self):
        self.site = Site.objects.get(is_default_site=True)
        self.url = reverse("commentail:discussion", args=[self.site.root_page_id])
        self.submit_url = reverse("commentail:submit", args=[self.site.root_page_id])
        self.user = get_user_model().objects.create_user("form-budget-author")
        self.client.force_login(self.user)

    def test_repeated_gets_stop_creating_tickets_but_keep_widget_readable(self):
        self.client.get(self.url)
        self.client.get(self.url)
        count = FormTicket.objects.count()
        response = self.client.get(self.url)
        self.assertEqual(FormTicket.objects.count(), count)
        self.assertContains(response, "Too many form requests")
        self.assertEqual(response.context["form_key"], "")
        self.assertContains(response, "disabled")
        self.assertIn("no-store", response["Cache-Control"])

    def test_valid_existing_ticket_can_still_submit_when_issuance_is_limited(self):
        form = self.client.get(self.url)
        self.client.get(self.url)
        response = self.client.post(
            self.submit_url,
            {"key": form.context["form_key"], "text": "Already open draft"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Comment.objects.get().text, "Already open draft")

    def test_invalid_native_post_keeps_draft_without_unbounded_recovery_tickets(self):
        self.client.get(self.url)
        self.client.get(self.url)
        count = FormTicket.objects.count()
        response = self.client.post(
            self.submit_url,
            {
                "text": "Keep this draft",
                "name": "Guest",
                "email": "guest@example.invalid",
            },
            HTTP_ACCEPT="text/html",
        )
        self.assertContains(response, "Keep this draft", status_code=400)
        self.assertContains(response, "Too many form requests", status_code=400)
        self.assertEqual(FormTicket.objects.count(), count)

    def test_new_session_cannot_reset_ip_budget_and_other_ip_is_independent(self):
        self.client.get(self.url)
        self.client.get(self.url)
        other = Client()
        self.assertEqual(other.get(self.url).context["form_key"], "")
        self.assertTrue(
            other.get(self.url, REMOTE_ADDR="192.0.2.2").context["form_key"]
        )

    def test_issuance_resumes_after_rolling_window(self):
        self.client.get(self.url)
        self.client.get(self.url)
        RateEvent.objects.filter(kind="form_ip").update(
            created_at=timezone.now() - timedelta(seconds=61)
        )
        self.assertTrue(self.client.get(self.url).context["form_key"])

    def test_retry_after_window_expiry_keeps_draft_and_restores_submission(self):
        self.client.get(self.url)
        self.client.get(self.url)
        refused = self.client.post(
            self.submit_url, {"refresh": "1", "text": "Keep while waiting"}
        )
        self.assertContains(refused, "Retry check")
        self.assertContains(refused, "Keep while waiting")
        self.assertEqual(refused.context["form_key"], "")
        RateEvent.objects.filter(kind="form_ip").update(
            created_at=timezone.now() - timedelta(seconds=61)
        )
        recovered = self.client.post(
            self.submit_url, {"refresh": "1", "text": "Keep while waiting"}
        )
        self.assertContains(recovered, "Keep while waiting")
        self.assertTrue(recovered.context["form_key"])
        self.assertNotContains(recovered, "Too many form requests")

    @override_settings(COMMENTAIL={"default": {"FORM_IP_LIMIT_PER_HOUR": 2}})
    def test_hourly_budget_survives_minute_window_expiry(self):
        self.client.get(self.url)
        self.client.get(self.url)
        RateEvent.objects.filter(kind="form_ip").update(
            created_at=timezone.now() - timedelta(seconds=61)
        )
        self.assertEqual(self.client.get(self.url).context["form_key"], "")
        self.assertEqual(FormTicket.objects.count(), 2)

    def test_guest_refusals_create_neither_tickets_nor_captchas(self):
        self.client.logout()
        self.client.get(self.url)
        self.client.get(self.url)
        tickets = FormTicket.objects.count()
        challenges = CaptchaChallenge.objects.count()
        events = RateEvent.objects.count()
        for _ in range(4):
            response = self.client.get(self.url)
            self.assertContains(response, "Too many form requests")
        self.assertEqual(FormTicket.objects.count(), tickets)
        self.assertEqual(CaptchaChallenge.objects.count(), challenges)
        self.assertEqual(RateEvent.objects.count(), events)
