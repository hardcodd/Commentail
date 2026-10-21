from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from wagtail.models import Site

from commentail.forms import DiscussionSettingsForm, SiteSettingsForm
from commentail.models import (
    Comment,
    Discussion,
    MailJob,
    ReplySubscription,
    SiteCommentSettings,
)
from commentail.outbox import process_mail
from commentail.services import moderate, submit


class AutomaticNotificationTests(TestCase):
    def setUp(self):
        self.site = Site.objects.get(is_default_site=True)
        self.discussion = Discussion.objects.create(site=self.site, page=self.site.root_page)
        self.author = get_user_model().objects.create_user("notification-author", email="reader@example.invalid")
        self.admin = get_user_model().objects.create_superuser("notification-admin", "admin@example.invalid", "synthetic")
        self.url = reverse("commentail:discussion", args=[self.site.root_page.pk])
        self.submit_url = reverse("commentail:submit", args=[self.site.root_page.pk])
        self.client.force_login(self.author)

    def post_comment(self):
        form = self.client.get(self.url)
        self.assertNotContains(form, 'name="subscribe"')
        key = form.context["form_key"]
        response = self.client.post(self.submit_url, {"key": key, "text": "Automatic notifications", "subscribe": "off"})
        self.assertEqual(response.status_code, 302)
        return Comment.objects.latest("pk")

    def test_public_submission_subscribes_without_checkbox_and_notice_is_once(self):
        comment = self.post_comment()
        self.assertTrue(ReplySubscription.objects.get(comment=comment).enabled)
        response = self.client.get(self.url)
        self.assertContains(response, "We’ll email you about replies.")
        self.assertContains(response, 'role="status"')
        self.assertNotContains(self.client.get(self.url), "We’ll email you about replies.")
        # Changing site settings never re-enables an explicit unsubscribe.
        ReplySubscription.objects.filter(comment=comment).update(enabled=False)
        self.client.get(self.url)
        self.assertFalse(ReplySubscription.objects.get(comment=comment).enabled)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend", EMAIL_HOST="")
    def test_unconfigured_mail_registered_comment_has_no_subscription_or_promise(self):
        comment = self.post_comment()
        self.assertFalse(ReplySubscription.objects.filter(comment=comment).exists())
        self.assertNotContains(self.client.get(self.url), "We’ll email you about replies.")

    def test_account_without_email_can_comment_without_mail_promise(self):
        self.author.email = ""
        self.author.save()
        comment = self.post_comment()
        self.assertFalse(ReplySubscription.objects.filter(comment=comment).exists())
        self.assertNotContains(self.client.get(self.url), "We’ll email you about replies.")

    def test_site_switch_defaults_on_and_has_no_page_override(self):
        self.assertTrue(SiteCommentSettings().email_enabled)
        self.assertIn("email_enabled", SiteSettingsForm().fields)
        self.assertNotIn("email_enabled", DiscussionSettingsForm().fields)

    def test_disabled_site_blocks_guests_but_allows_registered_without_mail(self):
        SiteCommentSettings.objects.create(site=self.site, email_enabled=False, notify_publication=True)
        comment = self.post_comment()
        moderate(comment.pk, "approve", actor=self.admin)
        self.assertFalse(ReplySubscription.objects.filter(comment=comment).exists())
        self.assertFalse(MailJob.objects.exists())
        self.client.logout()
        self.assertFalse(self.client.get(self.url).context["can_post"])
        response = self.client.post(self.submit_url, {"key": "invalid", "text": "Guest"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Comment.objects.count(), 1)

    def test_switch_cancels_already_queued_mail_and_blocks_new_jobs(self):
        options = SiteCommentSettings.objects.create(site=self.site, notify_publication=True)
        comment = submit(self.discussion.pk, text="Before disabling", user=self.author)
        moderate(comment.pk, "approve", actor=self.admin)
        self.assertTrue(MailJob.objects.filter(status="pending").exists())
        options.email_enabled = False
        options.save()
        with patch("commentail.outbox.deliver") as delivery:
            self.assertEqual(process_mail(), 0)
            delivery.assert_not_called()
        self.assertFalse(MailJob.objects.filter(status="pending").exists())
        after = submit(self.discussion.pk, text="After disabling", user=self.author)
        moderate(after.pk, "approve", actor=self.admin)
        self.assertFalse(MailJob.objects.filter(comment=after).exists())

    def test_disabled_site_does_not_suppress_another_sites_mail(self):
        SiteCommentSettings.objects.create(site=self.site, email_enabled=False)
        other_site = Site.objects.create(hostname="other.example.invalid", root_page=self.site.root_page)
        SiteCommentSettings.objects.create(site=other_site, notify_publication=True)
        discussion = Discussion.objects.create(site=other_site, page=self.site.root_page)
        comment = submit(discussion.pk, text="Another site", user=self.author)
        moderate(comment.pk, "approve", actor=self.admin)
        self.assertEqual(process_mail(), 1)
        self.assertEqual(MailJob.objects.get(comment=comment).status, "sent")
