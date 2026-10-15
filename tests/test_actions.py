from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.utils import timezone
from wagtail.models import PageViewRestriction, Site

from commentail.models import Discussion
from commentail.security import issue_token
from commentail.services import submit


class ActionViewTests(TestCase):
    def setUp(self):
        self.site = Site.objects.get(is_default_site=True)
        self.discussion = Discussion.objects.create(
            site=self.site, page=self.site.root_page
        )
        self.comment = submit(
            self.discussion.pk,
            text="Guest",
            guest_name="Guest",
            guest_email="guest@example.invalid",
        )
        self.secret = issue_token(
            self.comment, "confirm", timezone.now() + timedelta(hours=1)
        )
        self.url = "/commentail/actions/confirm/?token=" + self.secret

    def test_get_does_not_confirm(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.comment.refresh_from_db()
        self.assertEqual(self.comment.status, "awaiting_email")
        self.assertEqual(response["Referrer-Policy"], "no-referrer")
        self.assertIn("no-store", response["Cache-Control"])

    def test_post_requires_csrf(self):
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(client.post(self.url, {"token": self.secret}).status_code, 403)

    def test_post_confirms_and_remembers(self):
        response = self.client.post(self.url, {"token": self.secret})
        self.assertEqual(response.status_code, 200)
        self.comment.refresh_from_db()
        self.assertEqual(self.comment.status, "pending")
        cookie = response.cookies[f"commentail_guest_{self.site.pk}"]
        self.assertTrue(cookie["httponly"])
        self.assertEqual(cookie["samesite"], "Lax")
        self.assertNotIn("guest@example.invalid", cookie.value)

    def test_page_restriction_prevents_action(self):
        PageViewRestriction.objects.create(
            page=self.site.root_page, restriction_type="login"
        )
        self.assertEqual(
            self.client.post(self.url, {"token": self.secret}).status_code, 403
        )
        self.comment.refresh_from_db()
        self.assertEqual(self.comment.status, "awaiting_email")

    def test_invalid_purpose_does_not_disclose_comment(self):
        response = self.client.get("/commentail/actions/edit/?token=" + self.secret)
        self.assertEqual(response.status_code, 404)
        self.assertNotContains(response, "guest@example.invalid", status_code=404)
        self.assertEqual(response["Referrer-Policy"], "no-referrer")
        self.assertIn("no-store", response["Cache-Control"])

    def test_csrf_denial_also_protects_capability_headers(self):
        response = Client(enforce_csrf_checks=True).post(
            self.url, {"token": self.secret}
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response["Referrer-Policy"], "no-referrer")
        self.assertIn("no-store", response["Cache-Control"])

    def test_view_capability_shows_owner_text_without_confirmation(self):
        secret = issue_token(self.comment, "view", timezone.now() + timedelta(hours=1))
        response = self.client.get("/commentail/actions/view/?token=" + secret)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Guest")
        self.assertNotContains(response, "guest@example.invalid")
        self.comment.refresh_from_db()
        self.assertEqual(self.comment.status, "awaiting_email")

    def test_guest_edit_failure_preserves_draft_and_locked_form_is_removed(self):
        from commentail.services import confirm_email, moderate

        confirm_email(self.comment.pk)
        admin = get_user_model().objects.create_superuser(
            "draft-admin", "", "synthetic"
        )
        moderate(self.comment.pk, "approve", actor=admin)
        secret = issue_token(
            self.comment, "edit", timezone.now() + timedelta(minutes=15)
        )
        url = "/commentail/actions/edit/"
        response = self.client.post(url, {"token": secret, "text": " "})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.context["text"], " ")
        self.assertContains(response, 'name="text"', status_code=400)
        self.comment.edit_locked = True
        self.comment.save()
        response = self.client.get(url, {"token": secret})
        self.assertNotContains(response, 'name="text"')
        self.assertContains(response, "Comment cannot be edited")
