"""HTTP and worker regressions for security review findings."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from wagtail.models import Page, Site

from commentail.models import Discussion, MailJob
from commentail.outbox import process_mail
from commentail.security import issue_token
from commentail.services import submit


class SecurityBoundaryTests(TestCase):
    def setUp(self):
        self.site = Site.objects.get(is_default_site=True)
        self.foreign_root = Page.get_first_root_node().add_child(
            instance=Page(title="Foreign root", slug="foreign-security")
        )
        self.other = Site.objects.create(
            hostname="foreign.invalid", root_page=self.foreign_root
        )

    def test_foreign_page_cannot_create_a_discussion_on_this_site(self):
        response = self.client.get(
            reverse("commentail:discussion", args=[self.foreign_root.pk])
        )
        self.assertEqual(response.status_code, 404)
        self.assertFalse(
            Discussion.objects.filter(site=self.site, page=self.foreign_root).exists()
        )

    def test_foreign_page_revokes_existing_capabilities_and_queued_mail(self):
        discussion = Discussion.objects.create(site=self.site, page=self.foreign_root)
        comment = submit(
            discussion.pk,
            text="Moved private body",
            guest_name="Guest",
            guest_email="guest@example.invalid",
        )
        secret = issue_token(comment, "view", timezone.now() + timedelta(hours=1))
        response = self.client.get(
            reverse("commentail:action", args=["view"]), {"token": secret}
        )
        self.assertEqual(response.status_code, 403)
        self.assertNotContains(response, comment.text, status_code=403)
        self.assertEqual(process_mail(), 0)
        self.assertEqual(MailJob.objects.get(comment=comment).status, "cancelled")

    def test_public_path_ids_outside_database_range_are_404(self):
        for route, kwargs in (
            ("discussion", {"page_id": 2**63}),
            ("object_discussion", {"discussion_id": 2**63}),
            ("edit", {"identifier": 2**63}),
            ("resend", {"identifier": 2**63}),
        ):
            # Send literal oversized IDs through the real URL converters.
            path = reverse(
                "commentail:" + route, kwargs={key: 1 for key in kwargs}
            ).replace("/1/", f"/{2**63}/")
            with self.subTest(route=route):
                response = (
                    self.client.post(path)
                    if route == "resend"
                    else self.client.get(path)
                )
                self.assertEqual(response.status_code, 404)

    def test_admin_path_ids_outside_database_range_are_rejected(self):
        self.client.force_login(
            get_user_model().objects.create_superuser("security-admin", "", "test")
        )
        for route, kwargs in (
            ("detail", {"identifier": 1}),
            ("settings", {"site_id": 1}),
            ("object_settings", {"identifier": 1}),
            ("rule_edit", {"identifier": 1}),
        ):
            path = reverse("commentail_admin:" + route, kwargs=kwargs).replace(
                "/1/", f"/{2**63}/"
            )
            with self.subTest(route=route):
                self.assertIn(self.client.get(path).status_code, (403, 404))
