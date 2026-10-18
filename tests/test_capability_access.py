"""Issued capabilities never replace current target access or Site identity."""

from datetime import timedelta

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from wagtail.models import PageViewRestriction, Site

from commentail.models import Discussion, GuestGrant, MailJob, ReplySubscription
from commentail.security import issue_token
from commentail.services import submit
from tests.targets.models import Product
from tests.test_object_adapters import CONFIG


class CapabilityAccessTests(TestCase):
    def setUp(self):
        self.site = Site.objects.get(is_default_site=True)
        self.discussion = Discussion.objects.create(
            site=self.site, page=self.site.root_page
        )

    def guest_links(self):
        comment = submit(
            self.discussion.pk,
            text="Private capability body",
            guest_name="Synthetic guest",
            guest_email="capability@example.invalid",
            subscribe=True,
        )
        links = {
            purpose: issue_token(comment, purpose, timezone.now() + timedelta(hours=1))
            for purpose in ("confirm", "view", "edit", "unsubscribe")
        }
        return comment, links

    def assert_denied(self, comment, links, *, status=403, host="testserver"):
        jobs = MailJob.objects.count()
        for purpose in ("confirm", "view", "edit"):
            for method in ("get", "post"):
                with self.subTest(purpose=purpose, method=method, host=host):
                    response = getattr(self.client, method)(
                        reverse("commentail:action", args=[purpose]),
                        {"token": links[purpose], "text": "Unauthorized revision"},
                        HTTP_HOST=host,
                    )
                    self.assertEqual(response.status_code, status)
                    self.assertNotContains(response, comment.text, status_code=status)
                    self.assertNotContains(response, comment.email, status_code=status)
                    self.assertNotContains(response, "<form", status_code=status)
                    self.assertEqual(response["Referrer-Policy"], "strict-origin")
                    self.assertIn("no-store", response["Cache-Control"])
        comment.refresh_from_db()
        self.assertEqual(comment.status, "awaiting_email")
        self.assertFalse(comment.revisions.exists())
        self.assertEqual(MailJob.objects.count(), jobs)
        self.assertFalse(GuestGrant.objects.exists())
        self.assertNotIn("commentail_edits", self.client.session)

    def assert_unsubscribe_available(self, comment, links):
        url = reverse("commentail:action", args=["unsubscribe"])
        self.assertEqual(
            self.client.get(url, {"token": links["unsubscribe"]}).status_code, 200
        )
        self.assertTrue(ReplySubscription.objects.get(comment=comment).enabled)
        response = self.client.post(url, {"token": links["unsubscribe"]})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(ReplySubscription.objects.get(comment=comment).enabled)
        self.assertNotContains(response, comment.text)
        self.assertNotContains(response, comment.email)

    def test_page_restriction_revokes_issued_links_but_allows_unsubscribe(self):
        comment, links = self.guest_links()
        # Establish that these links were usable before access changed.
        self.assertContains(
            self.client.get(
                reverse("commentail:action", args=["view"]), {"token": links["view"]}
            ),
            comment.text,
        )
        PageViewRestriction.objects.create(
            page=self.site.root_page, restriction_type="login"
        )
        self.assert_denied(comment, links)
        self.assert_unsubscribe_available(comment, links)

    def test_unpublished_page_revokes_issued_links(self):
        comment, links = self.guest_links()
        page = self.site.root_page
        page.live = False
        page.save(update_fields=["live"])
        self.assert_denied(comment, links)
        self.assert_unsubscribe_available(comment, links)

    def test_every_capability_is_bound_to_original_site(self):
        comment, links = self.guest_links()
        Site.objects.create(hostname="other.invalid", root_page=self.site.root_page)
        self.assert_denied(comment, links, status=404, host="other.invalid")
        response = self.client.post(
            reverse("commentail:action", args=["unsubscribe"]),
            {"token": links["unsubscribe"]},
            HTTP_HOST="other.invalid",
        )
        self.assertEqual(response.status_code, 404)
        self.assertTrue(ReplySubscription.objects.get(comment=comment).enabled)

    @override_settings(COMMENTAIL=CONFIG)
    def test_object_access_changes_revoke_issued_links(self):
        from django.contrib.auth.models import AnonymousUser
        from django.test import RequestFactory

        from commentail.objects import get_object_discussion

        product = Product.objects.create(site=self.site, title="Capability target")
        request = RequestFactory().get("/")
        request.user = AnonymousUser()
        self.discussion = get_object_discussion(request, product)
        comment, links = self.guest_links()
        self.assertContains(
            self.client.get(
                reverse("commentail:action", args=["view"]), {"token": links["view"]}
            ),
            comment.text,
        )
        product.visible = False
        product.save(update_fields=["visible"])
        self.assert_denied(comment, links)
        product.visible = True
        product.save(update_fields=["visible"])
        for config in (
            {},
            {
                "default": {
                    "OBJECT_ADAPTERS": {
                        Product._meta.label: "tests.test_object_adapters.BrokenAdapter"
                    }
                }
            },
        ):
            with self.subTest(config=config), override_settings(COMMENTAIL=config):
                self.assert_denied(comment, links)
        other = Site.objects.create(
            hostname="moved.invalid", root_page=self.site.root_page
        )
        product.site = other
        product.save(update_fields=["site"])
        self.assert_denied(comment, links)
        self.assert_unsubscribe_available(comment, links)

    def test_revoked_page_access_invalidates_previously_opened_guest_editor(self):
        from django.contrib.auth import get_user_model

        from commentail.services import confirm_email, moderate

        comment, links = self.guest_links()
        confirm_email(comment.pk)
        admin = get_user_model().objects.create_superuser(
            "capability-admin", "", "test"
        )
        moderate(comment.pk, "approve", actor=admin)
        response = self.client.get(
            reverse("commentail:action", args=["edit"]), {"token": links["edit"]}
        )
        self.assertEqual(response.status_code, 303)
        self.assertIn(str(comment.pk), self.client.session["commentail_edits"])
        self.assertContains(
            self.client.get(response["Location"]), 'class="commentail-edit-form"'
        )
        PageViewRestriction.objects.create(
            page=self.site.root_page, restriction_type="login"
        )
        jobs = MailJob.objects.count()
        self.assertEqual(
            self.client.post(
                reverse("commentail:edit", args=[comment.pk]),
                {"text": "Unauthorized edit", "edit_comment": comment.pk},
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(
                reverse("commentail:action", args=["edit"]), {"token": links["edit"]}
            ).status_code,
            403,
        )
        comment.refresh_from_db()
        self.assertEqual(comment.text, "Private capability body")
        self.assertFalse(comment.revisions.exists())
        self.assertEqual(MailJob.objects.count(), jobs)
