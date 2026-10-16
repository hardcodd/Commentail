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
        self.assertEqual(response["Referrer-Policy"], "strict-origin")
        self.assertContains(response, 'name="referrer" content="strict-origin"')
        self.assertIn("no-store", response["Cache-Control"])

    def test_post_requires_csrf(self):
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(client.post(self.url, {"token": self.secret}).status_code, 403)

    def test_post_confirms_and_remembers(self):
        response = self.client.post(self.url, {"token": self.secret})
        self.assertEqual(response.status_code, 303)
        self.assertEqual(
            response["Location"],
            f"/?target={self.comment.pk}#commentail-{self.comment.pk}",
        )
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
        self.assertEqual(response["Referrer-Policy"], "strict-origin")
        self.assertIn("no-store", response["Cache-Control"])

    def test_csrf_denial_also_protects_capability_headers(self):
        response = Client(enforce_csrf_checks=True).post(
            self.url, {"token": self.secret}
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response["Referrer-Policy"], "strict-origin")
        self.assertIn("no-store", response["Cache-Control"])

    def test_view_capability_shows_owner_text_without_confirmation(self):
        secret = issue_token(self.comment, "view", timezone.now() + timedelta(hours=1))
        response = self.client.get("/commentail/actions/view/?token=" + secret)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Guest")
        self.assertNotContains(response, "guest@example.invalid")
        self.comment.refresh_from_db()
        self.assertEqual(self.comment.status, "awaiting_email")

    def test_https_origin_only_referrer_supports_csrf_without_token_disclosure(self):
        browser = Client(enforce_csrf_checks=True)
        page = browser.get(self.url, secure=True)
        response = browser.post(
            self.url,
            {
                "token": self.secret,
                "csrfmiddlewaretoken": browser.cookies["csrftoken"].value,
            },
            secure=True,
            HTTP_REFERER="https://testserver/",
        )
        self.assertEqual(page["Referrer-Policy"], "strict-origin")
        self.assertEqual(response.status_code, 303)
        self.comment.refresh_from_db()
        self.assertEqual(self.comment.status, "pending")

    def test_null_and_foreign_origins_remain_rejected_with_valid_csrf(self):
        browser = Client(enforce_csrf_checks=True)
        browser.get(self.url)
        for origin in ("null", "https://attacker.invalid"):
            with self.subTest(origin=origin):
                response = browser.post(
                    self.url,
                    {
                        "token": self.secret,
                        "csrfmiddlewaretoken": browser.cookies["csrftoken"].value,
                    },
                    HTTP_ORIGIN=origin,
                )
                self.assertEqual(response.status_code, 403)
        self.comment.refresh_from_db()
        self.assertEqual(self.comment.status, "awaiting_email")

    def test_guest_revision_redirects_to_host_without_exposing_capability(self):
        from commentail.services import confirm_email, moderate

        confirm_email(self.comment.pk)
        admin = get_user_model().objects.create_superuser("edit-admin", "", "synthetic")
        moderate(self.comment.pk, "approve", actor=admin)
        secret = issue_token(self.comment, "edit", timezone.now() + timedelta(minutes=15))
        response = self.client.post(
            "/commentail/actions/edit/",
            {"token": secret, "text": "Revised guest text"},
        )
        self.assertEqual(response.status_code, 303)
        self.assertEqual(
            response["Location"],
            f"/?target={self.comment.pk}#commentail-{self.comment.pk}",
        )
        self.assertNotIn(secret, response["Location"])
        self.assertEqual(self.comment.revisions.get().status, "pending")
        self.comment.refresh_from_db()
        self.assertEqual(self.comment.text, "Guest")
        self.assertIn("no-store", response["Cache-Control"])

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
        self.assertEqual(response.context["editing"]["text"], " ")
        self.assertContains(response, 'name="text"', status_code=400)
        self.comment.edit_locked = True
        self.comment.save(update_fields=["edit_locked"])
        response = self.client.get(url, {"token": secret}, follow=True)
        self.assertNotContains(response, 'class="commentail-edit-form"')
        self.assertContains(response, "Comment cannot be edited")

    def test_action_documents_share_local_overridable_layout(self):
        response = self.client.get(self.url)
        self.assertTemplateUsed(response, "commentail/base.html")
        self.assertContains(response, 'class="commentail-document"')
        self.assertContains(response, '<h1 id="commentail-page-title">Confirm email</h1>')
        self.assertContains(response, 'aria-labelledby="commentail-page-title"')
        self.assertContains(response, 'name="token"')
        self.assertContains(response, "Back to comments")
        self.assertNotContains(response, "fonts.googleapis")

    def test_invalid_capability_gets_styled_error_without_private_data_or_form(self):
        response = self.client.get("/commentail/actions/confirm/?token=invalid")
        self.assertEqual(response.status_code, 404)
        self.assertTemplateUsed(response, "commentail/base.html")
        self.assertContains(response, 'role="alert"', status_code=404)
        self.assertNotContains(response, '<form', status_code=404)
        self.assertNotContains(response, self.comment.text, status_code=404)
        self.assertNotContains(response, self.comment.email, status_code=404)
        self.assertIn("no-store", response["Cache-Control"])

    def test_unsubscribe_result_remains_styled_and_has_host_return(self):
        secret = issue_token(self.comment, "unsubscribe", timezone.now() + timedelta(days=1))
        response = self.client.post("/commentail/actions/unsubscribe/", {"token": secret})
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "commentail/base.html")
        self.assertContains(response, 'role="status"')
        self.assertNotContains(response, '<form')
        self.assertContains(response, f'/?target={self.comment.pk}#commentail-{self.comment.pk}')
