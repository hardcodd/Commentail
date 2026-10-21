"""Malformed public input must fail validation before reaching database fields."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from wagtail.models import Site

from commentail.models import Comment, Discussion
from commentail.services import DomainError, submit


class PublicInputBoundaryTests(TestCase):
    def setUp(self):
        self.site = Site.objects.get(is_default_site=True)
        self.discussion = Discussion.objects.create(site=self.site, page=self.site.root_page)
        self.user = get_user_model().objects.create_user("boundary-author")
        self.client.force_login(self.user)
        self.url = reverse("commentail:discussion", args=[self.site.root_page_id])

    def test_oversized_navigation_identifiers_are_ignored(self):
        for field in ("target", "reply_to", "edit_comment"):
            for value in ("9" * 5000, str(2**63), "0", "invalid"):
                with self.subTest(field=field, length=len(value)):
                    response = self.client.get(self.url, {field: value})
                    self.assertEqual(response.status_code, 200)
                    self.assertIsNone(response.context["reply_to"])
                    self.assertIsNone(response.context["editing"])

    def test_oversized_admin_identifiers_do_not_crash(self):
        admin = get_user_model().objects.create_superuser("boundary-admin", "", "test")
        self.client.force_login(admin)
        for route, field, status in (
            ("list", "site", 200), ("list", "page", 200),
            ("mail", "site", 200), ("objects", "site", 200),
            ("rules", "id", 400), ("access", "id", 400),
        ):
            with self.subTest(route=route, field=field):
                response = self.client.get(
                    reverse("commentail_admin:" + route), {field: "9" * 5000},
                )
                self.assertEqual(response.status_code, status)

    def test_oversized_reply_submission_is_a_validation_error(self):
        key = self.client.get(self.url).context["form_key"]
        response = self.client.post(
            reverse("commentail:submit", args=[self.site.root_page_id]),
            {"key": key, "text": "Draft", "reply_to": "9" * 5000},
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Comment.objects.exists())

    def test_null_bytes_are_rejected_before_persistence(self):
        for values in (
            {"text": "Text\x00suffix", "user": self.user},
            {"text": "Text", "guest_name": "Guest\x00suffix",
             "guest_email": "guest@example.invalid"},
        ):
            with self.subTest(values=values), self.assertRaises(DomainError):
                submit(self.discussion.pk, **values)
        self.assertFalse(Comment.objects.exists())

    def test_guest_email_cannot_exceed_the_storage_limit(self):
        email = "a" * 64 + "@" + ".".join(["b" * 60] * 3 + ["invalid"])
        self.assertEqual(len(email), 255)
        with self.assertRaises(DomainError):
            submit(self.discussion.pk, text="Guest", guest_name="Guest", guest_email=email)
        self.assertFalse(Comment.objects.exists())

    def test_native_invalid_draft_removes_null_bytes_before_json_storage(self):
        from commentail.models import FormTicket

        key = self.client.get(self.url).context["form_key"]
        response = self.client.post(
            reverse("commentail:submit", args=[self.site.root_page_id]),
            {"key": key, "text": "Draft\x00suffix"}, HTTP_ACCEPT="text/html",
        )
        self.assertEqual(response.status_code, 303)
        draft = FormTicket.objects.exclude(draft={}).get().draft
        self.assertEqual(draft["values"]["text"], "Draftsuffix")
        self.assertTrue(draft["error"])
        self.assertFalse(Comment.objects.exists())
