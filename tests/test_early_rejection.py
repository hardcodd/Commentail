"""Hard rules reject new guest text without mail while preserving correction."""

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import translation
from wagtail.models import Site

from commentail.models import (
    ActionToken,
    CaptchaChallenge,
    Comment,
    Discussion,
    MailJob,
    ModerationRule,
    SiteCommentSettings,
    SubmissionRecord,
)
from commentail.security import remember_guest
from commentail.services import DomainError, confirm_email, submit


class EarlyRejectionTests(TestCase):
    def setUp(self):
        self.site = Site.objects.get(is_default_site=True)
        self.discussion = Discussion.objects.create(
            site=self.site, page=self.site.root_page
        )
        self.options = SiteCommentSettings.objects.create(
            site=self.site, moderation="rules", notify_rejection=True
        )
        self.rule = ModerationRule.objects.create(
            phrase="ёлки палки",
            action="reject",
            reason="Please remove the forbidden phrase.",
        )
        self.url = reverse("commentail:submit", args=[self.site.root_page.pk])
        self.form_url = reverse("commentail:discussion", args=[self.site.root_page.pk])

    def guest(self, text):
        return submit(
            self.discussion.pk,
            text=text,
            guest_name="Guest",
            guest_email="guest@example.invalid",
        )

    def payload(self, text):
        form = self.client.get(self.form_url)
        challenge = form.context["captcha"]
        return {
            "key": form.context["form_key"],
            "text": text,
            "name": "Guest",
            "email": "guest@example.invalid",
            "challenge": str(challenge.id) if challenge else "",
            "answer": str(CaptchaChallenge.objects.get(pk=challenge.id).answer)
            if challenge
            else "",
        }

    def assert_no_submission(self):
        for model in (Comment, MailJob, ActionToken, SubmissionRecord):
            self.assertFalse(model.objects.exists(), model.__name__)

    def test_guest_rejection_uses_normalization_and_creates_no_mail_or_comment(self):
        with self.assertRaisesMessage(DomainError, self.rule.reason):
            self.guest("ЕЛКИ,\n ПАЛКИ")
        self.assert_no_submission()

    def test_lowest_id_reason_wins_across_positions_and_normalized_duplicates(self):
        ModerationRule.objects.create(
            phrase="first", action="reject", reason="Later rule"
        )
        ModerationRule.objects.create(
            phrase="елки палки", action="reject", reason="Duplicate"
        )
        with self.assertRaisesMessage(DomainError, self.rule.reason):
            self.guest("first елки палки")

    def test_default_reason_is_localized(self):
        self.rule.reason = ""
        self.rule.save()
        with (
            translation.override("ru"),
            self.assertRaisesMessage(
                DomainError, "Текст не соответствует правилам обсуждения."
            ),
        ):
            self.guest("елки палки")

    def test_configured_reason_is_literal_even_if_it_matches_a_translation_key(self):
        self.rule.reason = "Permission denied"
        self.rule.save()
        with (
            translation.override("ru"),
            self.assertRaisesMessage(DomainError, "Permission denied"),
        ):
            self.guest("елки палки")

    def test_captcha_is_still_required_before_revealing_rule_reason(self):
        payload = self.payload("елки палки")
        payload["answer"] = "wrong"
        response = self.client.post(self.url, payload)
        self.assertEqual(response.status_code, 400)
        self.assertNotContains(response, self.rule.reason, status_code=400)
        self.assert_no_submission()

    def test_remembered_guest_is_still_refused_without_creating_mail(self):
        self.client.cookies[f"commentail_guest_{self.site.pk}"] = remember_guest(
            self.site, "guest@example.invalid"
        )
        response = self.client.post(self.url, self.payload("елки палки"))
        self.assertContains(response, self.rule.reason, status_code=400)
        self.assert_no_submission()

    def test_empty_reason_falls_back_and_disabled_or_other_policy_does_not_block(self):
        self.rule.reason = "   "
        self.rule.save()
        with self.assertRaisesMessage(
            DomainError, "Text does not comply with the discussion rules."
        ):
            self.guest("елки палки")
        self.rule.enabled = False
        self.rule.save()
        self.assertEqual(self.guest("елки палки").status, "awaiting_email")
        self.rule.enabled = True
        self.rule.save()
        self.discussion.moderation = "all"
        self.discussion.save()
        self.assertEqual(self.guest("елки палки").status, "awaiting_email")

    def test_review_rules_still_require_email_and_recheck_rules_at_confirmation(self):
        self.rule.action = "review"
        self.rule.save()
        comment = self.guest("елки палки")
        self.assertEqual(comment.status, "awaiting_email")
        self.assertEqual(MailJob.objects.get().kind, "confirm")
        self.rule.action = "reject"
        self.rule.save()
        self.assertEqual(confirm_email(comment.pk).status, "rejected")

    def test_fragment_error_preserves_text_escapes_reason_and_allows_correction(self):
        self.rule.reason = "Remove <script>alert(1)</script>"
        self.rule.save()
        response = self.client.post(self.url, self.payload("ЕЛКИ ПАЛКИ"))
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "ЕЛКИ ПАЛКИ", status_code=400)
        self.assertContains(response, "Remove &lt;script&gt;", status_code=400)
        self.assertNotContains(response, "<script>alert(1)</script>", status_code=400)
        self.assert_no_submission()
        self.assertEqual(
            self.client.post(self.url, self.payload("Corrected text")).status_code, 302
        )
        self.assertEqual(Comment.objects.get().status, "awaiting_email")

    def test_document_error_preserves_private_draft_without_javascript(self):
        response = self.client.post(
            self.url, self.payload("ЕЛКИ ПАЛКИ"), HTTP_ACCEPT="text/html"
        )
        self.assertEqual(response.status_code, 303)
        recovered = self.client.get(response.url)
        self.assertContains(recovered, "ЕЛКИ ПАЛКИ")
        self.assertContains(recovered, self.rule.reason)
        self.assert_no_submission()
        other = self.client_class()
        self.assertNotContains(other.get(response.url), "ЕЛКИ ПАЛКИ")

    @override_settings(COMMENTAIL={"default": {"GUEST_ATTEMPTS_PER_MINUTE": 1}})
    def test_early_rejection_does_not_refund_attempt_budget(self):
        response = self.client.post(self.url, self.payload("елки палки"))
        self.assertEqual(response.status_code, 400)
        response = self.client.post(self.url, self.payload("Corrected text"))
        self.assertEqual(response.status_code, 400)
        self.assertNotEqual(response.context["error"], self.rule.reason)
        self.assert_no_submission()
