"""Editing belongs in the host document, including emailed guest capabilities."""

from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

from bs4 import BeautifulSoup
from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone
from wagtail.models import Site

from commentail.models import Discussion
from commentail.security import issue_token
from commentail.services import moderate, submit


class InlineEditTests(TestCase):
    def setUp(self):
        self.site = Site.objects.get(is_default_site=True)
        self.discussion = Discussion.objects.create(
            site=self.site, page=self.site.root_page
        )
        self.author = get_user_model().objects.create_superuser(
            "inline-author", "", "synthetic"
        )
        self.client.force_login(self.author)
        self.comment = submit(
            self.discussion.pk, text="Original editable text", user=self.author
        )
        moderate(self.comment.pk, "approve", actor=self.author)
        self.url = reverse("commentail:edit", args=[self.comment.pk])

    def test_legacy_get_redirects_and_host_contains_inline_form(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(
            parse_qs(urlsplit(response["Location"]).query)["edit_comment"],
            [str(self.comment.pk)],
        )
        host = self.client.get(response["Location"])
        self.assertTemplateUsed(host, "wagtailcore/page.html")
        self.assertTemplateNotUsed(host, "commentail/edit.html")
        markup = BeautifulSoup(host.content, "html.parser")
        form = markup.select_one(f"#commentail-{self.comment.pk} .commentail-edit-form")
        self.assertIsNotNone(form)
        self.assertEqual(form.select_one("textarea").text, self.comment.text)
        self.assertEqual(markup.select_one(".commentail-form textarea").text, "")
        cancelled = self.client.get(
            form.select_one("a[data-commentail-edit-cancel]")["href"]
        )
        self.assertNotContains(cancelled, 'class="commentail-edit-form"')

    def test_native_invalid_revision_returns_private_draft_to_host(self):
        response = self.client.post(
            self.url,
            {"text": " ", "edit_comment": self.comment.pk},
            HTTP_ACCEPT="text/html",
        )
        self.assertEqual(response.status_code, 303)
        host = self.client.get(response["Location"])
        self.assertContains(host, "Comment is empty or too long")
        markup = BeautifulSoup(host.content, "html.parser")
        self.assertEqual(markup.select_one(".commentail-edit-form textarea").text, " ")
        self.assertEqual(markup.select_one(".commentail-form textarea").text, "")
        stranger = Client().get(response["Location"])
        self.assertNotContains(stranger, "Comment is empty or too long")
        self.assertNotContains(stranger, 'class="commentail-edit-form"')
        self.assertFalse(self.comment.revisions.exists())

    def test_guest_email_link_opens_host_and_session_proof_is_not_transferable(self):
        guest = submit(
            self.discussion.pk,
            text="Guest original",
            guest_name="Guest",
            guest_email="guest@example.invalid",
        )
        guest.status = "published"
        guest.published_at = timezone.now()
        guest.save()
        secret = issue_token(guest, "edit", timezone.now() + timedelta(minutes=15))
        browser = Client()
        response = browser.get("/commentail/actions/edit/", {"token": secret})
        self.assertEqual(response.status_code, 303)
        self.assertNotIn(secret, response["Location"])
        host = browser.get(response["Location"])
        self.assertNotContains(host, secret)
        form = BeautifulSoup(host.content, "html.parser").select_one(
            ".commentail-edit-form"
        )
        self.assertIsNotNone(form)
        self.assertEqual(
            Client().post(form["action"], {"text": "Attack"}).status_code, 404
        )
        accepted = browser.post(
            form["action"], {"text": "Guest revised", "edit_comment": guest.pk}
        )
        self.assertEqual(accepted.status_code, 303)
        self.assertEqual(guest.revisions.get().text, "Guest revised")
        guest.refresh_from_db()
        self.assertEqual(guest.text, "Guest original")

    def test_expired_guest_proof_does_not_authorize_host_or_post(self):
        from commentail.models import ActionToken
        from commentail.security import digest

        guest = submit(
            self.discussion.pk,
            text="Guest",
            guest_name="Guest",
            guest_email="guest@example.invalid",
        )
        guest.status = "published"
        guest.published_at = timezone.now()
        guest.save()
        secret = issue_token(guest, "edit", timezone.now() + timedelta(minutes=15))
        browser = Client()
        response = browser.get("/commentail/actions/edit/", {"token": secret})
        ActionToken.objects.filter(digest=digest(secret)).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        self.assertNotContains(
            browser.get(response["Location"]), 'class="commentail-edit-form"'
        )
        self.assertEqual(
            browser.post(
                reverse("commentail:edit", args=[guest.pk]), {"text": "Expired"}
            ).status_code,
            404,
        )
        self.assertFalse(guest.revisions.exists())

    def test_csrf_edit_failure_preserves_inline_draft_without_mutation(self):
        from django.test import override_settings

        browser = Client(enforce_csrf_checks=True)
        browser.force_login(self.author)
        with override_settings(CSRF_FAILURE_VIEW="commentail.public.csrf_failure"):
            response = browser.post(
                self.url, {"text": "Private revision draft"}, HTTP_ACCEPT="text/html"
            )
            self.assertEqual(response.status_code, 303)
            host = browser.get(response["Location"])
        self.assertContains(host, "Private revision draft")
        self.assertContains(host, "The form could not be verified")
        self.assertFalse(self.comment.revisions.exists())

    def test_forged_inline_target_and_hidden_field_cannot_edit_other_comments(self):
        other = get_user_model().objects.create_user("other-inline-author")
        comment = submit(self.discussion.pk, text="Other author's text", user=other)
        moderate(comment.pk, "approve", actor=self.author)
        host = self.client.get("/", {"edit_comment": comment.pk})
        self.assertNotContains(host, 'class="commentail-edit-form"')
        response = self.client.post(
            self.url, {"text": "Own revision", "edit_comment": comment.pk}
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.comment.revisions.get().text, "Own revision")
        self.assertFalse(comment.revisions.exists())

    def test_edit_disclosure_is_named_native_and_only_for_eligible_owner(self):
        host = self.client.get("/")
        markup = BeautifulSoup(host.content, "html.parser")
        menu = markup.select_one(
            f"#commentail-{self.comment.pk} details.commentail-menu"
        )
        self.assertIsNotNone(menu)
        self.assertEqual(menu.select_one("summary")["aria-label"], "Comment actions")
        self.assertIsNotNone(menu.select_one("a[data-commentail-edit]"))
        self.client.logout()
        self.assertNotContains(self.client.get("/"), 'class="commentail-menu"')
