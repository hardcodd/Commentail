from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from wagtail.models import PageViewRestriction, Site

from commentail.models import Discussion, SiteCommentSettings
from commentail.services import moderate, submit


class PublicInterfaceTests(TestCase):
    def setUp(self):
        self.site = Site.objects.get(is_default_site=True)
        self.discussion = Discussion.objects.create(
            site=self.site, page=self.site.root_page
        )
        self.admin = get_user_model().objects.create_superuser(
            "admin", "admin@example.invalid", "synthetic"
        )
        self.user = get_user_model().objects.create_user("writer")
        self.url = reverse("commentail:discussion", args=[self.site.root_page.pk])

    def assert_fragment(self, response, *, status=200):
        self.assertEqual(response.status_code, status)
        self.assertTemplateUsed(response, "commentail/block.html")
        content = response.content.decode().lower()
        self.assertNotRegex(content, r"<!doctype|<(?:html|head|body|link)(?:\s|>)")
        from bs4 import BeautifulSoup

        for script in BeautifulSoup(response.content, "html.parser").select("script"):
            self.assertEqual(script.get("type"), "application/ld+json")
            self.assertFalse(script.has_attr("src"))
        self.assertContains(response, f'data-discussion="{self.discussion.pk}"', status_code=status)

    def test_service_returns_only_widget_fragment(self):
        self.assert_fragment(self.client.get(self.url))

    def test_reply_exposes_independent_main_ticket_and_native_fallback(self):
        import re
        from unittest.mock import patch

        from commentail.admission import accept_request

        self.client.force_login(self.user)
        parent = submit(self.discussion.pk, text="Parent", user=self.admin)
        moderate(parent.pk, "approve", actor=self.admin)
        response = self.client.get(self.url, {"reply_to": parent.pk, "target": parent.pk})
        self.assertContains(response, f'data-reply-to="{parent.pk}"')
        self.assertContains(response, 'class="commentail-main-template"')
        self.assertContains(response, 'data-commentail-cancel')
        self.assertContains(response, f'id="commentail-reply-length-{parent.pk}"')
        self.assertNotEqual(response.context["form_key"], response.context["main_form_key"])
        keys = re.findall(r'name="key" value="([^"]+)"', response.content.decode())
        self.assertEqual(len(keys), 2)
        self.assertEqual(len(set(keys)), 2)
        # Both tickets must remain usable and deduplicate their own submission.
        first = self.client.post(
            reverse("commentail:submit", args=[self.site.root_page.pk]),
            {"key": response.context["form_key"], "text": "Reply", "reply_to": parent.pk},
        )
        self.assertEqual(first.status_code, 302)
        with patch("commentail.admission.consume"):
            main = accept_request(
                response.wsgi_request, self.discussion.pk,
                response.context["main_form_key"], text="Separate main comment",
            )
        self.assertIsNone(main.reply_to_id)

    def test_failed_progressive_post_keeps_navigation_on_host(self):
        from urllib.parse import urlsplit

        from bs4 import BeautifulSoup

        self.client.force_login(self.user)
        parent = submit(self.discussion.pk, text="Parent", user=self.user)
        moderate(parent.pk, "approve", actor=self.admin)
        child = submit(self.discussion.pk, text="Child", user=self.admin, reply_to=parent.pk)
        moderate(child.pk, "approve", actor=self.admin)
        submit_url = reverse("commentail:submit", args=[self.site.root_page.pk])
        for data in ({"text": " "}, {"refresh": "1", "text": "Draft"}):
            with self.subTest(data=data):
                key = self.client.get(self.url).context["form_key"]
                response = self.client.post(submit_url, {"key": key, **data})
                markup = BeautifulSoup(response.content, "html.parser")
                navigation = markup.select("a[data-commentail-navigation], a[data-commentail-cancel]")
                self.assertTrue(navigation)
                for link in navigation:
                    self.assertEqual(urlsplit(link["href"]).path, "/")

    def test_reply_error_keeps_nested_addressee_rendered(self):
        self.client.force_login(self.user)
        parent = submit(self.discussion.pk, text="Parent", user=self.admin)
        moderate(parent.pk, "approve", actor=self.admin)
        child = submit(self.discussion.pk, text="Child", user=self.admin, reply_to=parent.pk)
        moderate(child.pk, "approve", actor=self.admin)
        form = self.client.get(self.url, {"reply_to": child.pk, "target": child.pk})
        response = self.client.post(
            reverse("commentail:submit", args=[self.site.root_page.pk]),
            {"key": form.context["form_key"], "text": " ", "reply_to": child.pk},
        )
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, f'id="commentail-{child.pk}"', status_code=400)
        self.assertContains(response, f'data-reply-to="{child.pk}"', status_code=400)

    @override_settings(
        CSRF_FAILURE_VIEW="commentail.public.csrf_failure",
        EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
        EMAIL_HOST="127.0.0.1",
    )
    def test_login_rotated_form_preserves_draft_and_requires_resubmission(self):
        from django.middleware.csrf import get_token
        from django.test import Client

        browser = Client(enforce_csrf_checks=True)
        original = browser.get(self.url)
        old_token = get_token(original.wsgi_request)
        login = browser.post(
            reverse("wagtailadmin_login"),
            {
                "username": self.admin.username,
                "password": "synthetic",
                "csrfmiddlewaretoken": old_token,
            },
        )
        self.assertEqual(login.status_code, 302)
        url = reverse("commentail:submit", args=[self.site.root_page.pk])
        response = browser.post(
            url,
            {
                "key": original.context["form_key"],
                "text": "Preserved after login",
                "csrfmiddlewaretoken": old_token,
            },
        )
        self.assertEqual(response.status_code, 403)
        self.assertContains(response, "Preserved after login", status_code=403)
        self.assert_fragment(response, status=403)
        self.assertEqual(self.discussion.comments.count(), 0)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        response = browser.post(
            url,
            {
                "key": response.context["form_key"],
                "text": "Preserved after login",
                "csrfmiddlewaretoken": get_token(response.wsgi_request),
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.discussion.comments.count(), 1)

    @override_settings(CSRF_FAILURE_VIEW="commentail.public.csrf_failure")
    def test_foreign_origin_is_still_rejected(self):
        from django.middleware.csrf import get_token
        from django.test import Client

        browser = Client(enforce_csrf_checks=True)
        browser.force_login(self.user)
        original = browser.get(self.url)
        response = browser.post(
            reverse("commentail:submit", args=[self.site.root_page.pk]),
            {
                "key": original.context["form_key"],
                "text": "Origin attack",
                "csrfmiddlewaretoken": get_token(original.wsgi_request),
            },
            HTTP_ORIGIN="https://attacker.invalid",
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.discussion.comments.count(), 0)

    @override_settings(CSRF_FAILURE_VIEW="commentail.public.csrf_failure")
    def test_host_csrf_failure_outside_submission_keeps_default_behavior(self):
        from django.test import Client

        browser = Client(enforce_csrf_checks=True)
        response = browser.post(reverse("commentail:action", args=["confirm"]), {})
        self.assertEqual(response.status_code, 403)
        self.assertNotContains(response, 'name="key"', status_code=403)

    def test_public_never_receives_pending_text_or_email(self):
        submit(self.discussion.pk, text="PRIVATE PENDING TEXT", user=self.user)
        response = self.client.get(self.url)
        self.assertNotContains(response, "PRIVATE PENDING TEXT")
        self.assertNotContains(response, "example.invalid")

    def test_account_owner_sees_own_pending(self):
        submit(self.discussion.pk, text="OWNER PENDING", user=self.user)
        self.client.force_login(self.user)
        self.assertContains(self.client.get(self.url), "OWNER PENDING")

    def test_no_js_submission_uses_session_bound_form_and_redirect(self):
        self.client.force_login(self.user)
        response = self.client.get("/", HTTP_ACCEPT="text/html")
        key = response.context["form_key"]
        response = self.client.post(
            reverse("commentail:submit", args=[self.site.root_page.pk]),
            {"key": key, "text": "A plain comment"},
            HTTP_USER_AGENT="Synthetic browser",
            HTTP_ACCEPT="text/html",
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.discussion.comments.count(), 1)

        response = self.client.post(
            reverse("commentail:submit", args=[self.site.root_page.pk]),
            {"key": key, "text": "A plain comment"},
            HTTP_USER_AGENT="Synthetic browser",
            HTTP_ACCEPT="text/html",
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.discussion.comments.count(), 1)
        host = self.client.get(response["Location"], HTTP_ACCEPT="text/html")
        self.assertContains(host, "A plain comment")
        self.assertTemplateUsed(host, "wagtailcore/page.html")

    def test_submission_and_permalink_return_to_the_host_page(self):
        self.client.force_login(self.user)
        key = self.client.get(self.url).context["form_key"]
        response = self.client.post(
            reverse("commentail:submit", args=[self.site.root_page.pk]),
            {"key": key, "text": "Keep the reader in the article"},
        )
        comment = self.discussion.comments.get()
        expected = f"/?target={comment.pk}#commentail-{comment.pk}"
        self.assertEqual(response["Location"], expected)
        moderate(comment.pk, "approve", actor=self.admin)
        rendered = self.client.get(self.url)
        self.assertContains(rendered, f'href="{expected}"')
        self.assert_fragment(rendered)
        edit = self.client.post(
            reverse("commentail:edit", args=[comment.pk]), {"text": "Revised"}
        )
        self.assertEqual(edit["Location"], expected)

    def test_browser_navigation_to_service_url_redirects_to_article(self):
        response = self.client.get(
            self.url, {"target": "11", "thread": "2", "replies": "signed-window"},
            HTTP_SEC_FETCH_DEST="document"
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/?thread=2&replies=signed-window&target=11#commentail-11")

    def test_browser_validation_returns_to_article_with_private_persistent_draft(self):
        from django.test import Client

        self.client.force_login(self.user)
        parent = submit(self.discussion.pk, text="Parent", user=self.admin)
        moderate(parent.pk, "approve", actor=self.admin)
        key = self.client.get(self.url).context["form_key"]
        response = self.client.post(
            reverse("commentail:submit", args=[self.site.root_page.pk]),
            {"key": key, "text": " ", "reply_to": parent.pk, "subscribe": "on"},
            HTTP_ACCEPT="text/html",
        )
        self.assertEqual(response.status_code, 303)
        self.assertTrue(response["Location"].startswith("/?commentail_draft="))
        for _ in range(2):
            host = self.client.get(response["Location"])
            self.assertContains(host, "Comment is empty or too long")
            self.assertContains(host, f'name="reply_to" value="{parent.pk}"')
            self.assertNotContains(host, 'name="subscribe"')
        from bs4 import BeautifulSoup

        markup = BeautifulSoup(host.content, "html.parser")
        cancel = next(link for link in markup.select(".commentail-form a") if link.text == "Cancel")
        cancelled = self.client.get(cancel["href"])
        self.assertNotContains(cancelled, 'name="reply_to"')
        self.assertNotContains(cancelled, 'name="subscribe"')
        stranger = Client().get(response["Location"])
        self.assertNotContains(stranger, "Comment is empty or too long")
        self.assertNotContains(stranger, 'name="reply_to"')

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
        EMAIL_HOST="127.0.0.1",
    )
    def test_browser_captcha_refresh_returns_to_article_preserving_form(self):
        response = self.client.post(
            reverse("commentail:submit", args=[self.site.root_page.pk]),
            {"refresh": "1", "text": "Guest draft stays here", "name": "Reader",
             "email": "reader@example.invalid", "subscribe": "on"},
            HTTP_ACCEPT="text/html",
        )
        self.assertEqual(response.status_code, 303)
        self.assertNotIn("reader@example.invalid", response["Location"])
        host = self.client.get(response["Location"])
        self.assertContains(host, "Guest draft stays here")
        self.assertContains(host, 'value="reader@example.invalid"')
        self.assertContains(host, 'name="challenge"')
        from django.test import Client

        self.assertNotContains(Client().get(response["Location"]), "Guest draft stays here")

    def test_recovery_expires_and_successful_acceptance_clears_private_drafts(self):
        from datetime import timedelta

        from django.utils import timezone

        from commentail.models import FormTicket

        self.client.force_login(self.user)
        SiteCommentSettings.objects.create(site=self.site, max_length=3)

        def invalid_submission():
            key = self.client.get(self.url).context["form_key"]
            return self.client.post(
                reverse("commentail:submit", args=[self.site.root_page.pk]),
                {"key": key, "text": "Long private draft"}, HTTP_ACCEPT="text/html",
            )

        expired = invalid_submission()
        FormTicket.objects.exclude(draft={}).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        self.assertNotContains(self.client.get(expired["Location"]), "Long private draft")
        current = invalid_submission()
        host = self.client.get(current["Location"])
        self.assertContains(host, "Long private draft")
        self.assertNotIn("Long private draft", str(dict(self.client.session)))
        # Use the actual freshly rendered form, never the private recovery ticket.
        from bs4 import BeautifulSoup

        form = BeautifulSoup(host.content, "html.parser").select_one("form.commentail-form")
        response = self.client.post(form["action"], {
            "key": form.select_one('input[name="key"]')["value"], "text": "OK"
        }, HTTP_ACCEPT="text/html")
        self.assertEqual(response.status_code, 302)
        self.assertFalse(FormTicket.objects.exclude(draft={}).exists())
        self.assertNotContains(self.client.get(current["Location"]), "Long private draft")

    @override_settings(CSRF_FAILURE_VIEW="commentail.public.csrf_failure")
    def test_browser_csrf_error_returns_to_host_without_accepting_the_draft(self):
        from django.test import Client

        browser = Client(enforce_csrf_checks=True)
        browser.force_login(self.user)
        key = browser.get(self.url).context["form_key"]
        response = browser.post(
            reverse("commentail:submit", args=[self.site.root_page.pk]),
            {"key": key, "text": "Keep this after CSRF rejection"},
            HTTP_ACCEPT="text/html",
        )
        self.assertEqual(response.status_code, 303)
        self.assertFalse(self.discussion.comments.exists())
        host = browser.get(response["Location"])
        self.assertContains(host, "Keep this after CSRF rejection")
        self.assertContains(host, "The form could not be verified.")

    def test_validation_returns_only_widget_fragment(self):
        self.client.force_login(self.user)
        key = self.client.get(self.url).context["form_key"]
        response = self.client.post(
            reverse("commentail:submit", args=[self.site.root_page.pk]),
            {"key": key, "text": " "},
        )
        self.assert_fragment(response, status=400)

    def test_progressive_fragment_has_identity_and_localized_failure_message(self):
        comment = submit(self.discussion.pk, text="Navigation target", user=self.user)
        moderate(comment.pk, "approve", actor=self.admin)
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        self.assertContains(response, f'data-discussion="{self.discussion.pk}"')
        self.assertContains(response, "data-commentail-navigation")
        self.assertContains(response, "data-network-error=")

    def test_page_access_checked_for_reading_and_submission(self):
        PageViewRestriction.objects.create(
            page=self.site.root_page, restriction_type="login"
        )
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.assertEqual(
            self.client.post(
                reverse("commentail:submit", args=[self.site.root_page.pk]), {}
            ).status_code,
            404,
        )

    def test_hidden_discussion_renders_no_text_or_form(self):
        self.discussion.mode = "hidden"
        self.discussion.save()
        response = self.client.get(self.url)
        self.assertNotContains(response, "<form")
        self.assertNotContains(response, "textarea")

    def test_plain_text_and_only_http_links(self):
        SiteCommentSettings.objects.create(site=self.site, clickable_links=True)
        comment = submit(
            self.discussion.pk,
            text="<script>alert(1)</script> https://example.org javascript:evil mailto:a@b.test",
            user=self.user,
        )
        moderate(comment.pk, "approve", actor=self.admin)
        response = self.client.get(self.url)
        self.assertContains(response, "&lt;script&gt;")
        self.assertContains(response, 'href="https://example.org"')
        self.assertNotContains(response, 'href="javascript:')
        self.assertNotContains(response, 'href="mailto:')
        self.assertContains(response, 'rel="nofollow ugc noopener noreferrer"')

    def test_target_reply_beyond_first_batch_is_visible(self):
        parent = submit(self.discussion.pk, text="Parent", user=self.user)
        moderate(parent.pk, "approve", actor=self.admin)
        for i in range(25):
            reply = submit(
                self.discussion.pk,
                text=f"Reply {i}",
                user=self.user,
                reply_to=parent.pk,
            )
            moderate(reply.pk, "approve", actor=self.admin)
        response = self.client.get(self.url, {"target": reply.pk})
        self.assertContains(response, "Reply 24")
        self.assertContains(response, f'id="commentail-{reply.pk}"')

    def test_failed_reply_submission_preserves_addressee_and_navigation(self):
        parent = submit(self.discussion.pk, text="Parent", user=self.user)
        moderate(parent.pk, "approve", actor=self.admin)
        self.client.force_login(self.user)
        response = self.client.get(self.url, {"reply_to": parent.pk})
        response = self.client.post(
            reverse("commentail:submit", args=[self.site.root_page.pk]),
            {"key": response.context["form_key"], "text": " ", "reply_to": parent.pk},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.context["reply_to"]["id"], parent.pk)
        self.assertNotContains(response, "/submit/?", status_code=400)

    def test_closed_and_locked_edits_have_no_form_or_link(self):
        comment = submit(self.discussion.pk, text="Original", user=self.user)
        moderate(comment.pk, "approve", actor=self.admin)
        self.client.force_login(self.user)
        edit = reverse("commentail:edit", args=[comment.pk])
        self.discussion.mode = "read_only"
        self.discussion.save()
        self.assertNotContains(self.client.get(self.url), f'href="{edit}"')
        response = self.client.get(edit, follow=True)
        self.assertNotContains(response, 'class="commentail-edit-form"')
        self.assertEqual(response.headers["Cache-Control"], "private, no-store")
        self.discussion.mode = "open"
        self.discussion.save()
        comment.edit_locked = True
        comment.save()
        self.assertNotContains(self.client.get(edit, follow=True), 'class="commentail-edit-form"')

    def test_authenticated_edit_is_owner_only(self):
        comment = submit(self.discussion.pk, text="Original", user=self.user)
        moderate(comment.pk, "approve", actor=self.admin)
        self.client.force_login(self.admin)
        url = reverse("commentail:edit", args=[comment.pk])
        self.assertEqual(self.client.post(url, {"text": "Attack"}).status_code, 404)
        self.client.force_login(self.user)
        self.assertEqual(
            self.client.post(url, {"text": "Own revision"}).status_code, 302
        )
        self.assertEqual(comment.revisions.get().status, "pending")
        owner_response = self.client.get(self.url)
        self.assertContains(owner_response, "Own revision")
        self.assertContains(owner_response, "Original")
        self.client.logout()
        self.assertNotContains(self.client.get(self.url), "Own revision")

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend", EMAIL_HOST="")
    def test_guest_refresh_preserves_input_without_submission(self):
        response = self.client.get(self.url)
        self.assertIsNone(response.context["captcha"])
        # SMTP availability is configuration, no mail is sent in the HTTP request.
        with override_settings(
            EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
            EMAIL_HOST="127.0.0.1",
        ):
            response = self.client.get(self.url)
            challenge = response.context["captcha"]
            response = self.client.post(
                reverse("commentail:submit", args=[self.site.root_page.pk]),
                {
                    "refresh": "1",
                    "text": "Keep this draft",
                    "key": response.context["form_key"],
                },
            )
            self.assertContains(response, "Keep this draft")
            self.assert_fragment(response)
            self.assertNotEqual(challenge.id, response.context["captcha"].id)
            self.assertEqual(self.discussion.comments.count(), 0)

    def test_signed_window_does_not_pull_new_publications_into_next_batch(self):
        for i in range(25):
            comment = submit(self.discussion.pk, text=f"Existing {i}", user=self.user)
            moderate(comment.pk, "approve", actor=self.admin)
        response = self.client.get(self.url)
        self.assertEqual(len(response.context["rows"]), 20)
        more = response.context["more_url"]
        comment = submit(self.discussion.pk, text="NEW AFTER SNAPSHOT", user=self.user)
        moderate(comment.pk, "approve", actor=self.admin)
        response = self.client.get(more)
        self.assertEqual(len(response.context["rows"]), 25)
        self.assertNotContains(response, "NEW AFTER SNAPSHOT")
        self.assertContains(self.client.get(self.url), "NEW AFTER SNAPSHOT")

    def test_russian_ui_is_translated(self):
        from django.utils.translation import override

        with override("ru"):
            response = self.client.get(self.url)
            self.assertContains(response, "Комментарии")
            self.assertNotContains(response, "No published comments yet.")

    def test_resend_requires_browser_ownership_and_preserves_deadline(self):
        from commentail.models import MailJob

        comment = submit(
            self.discussion.pk,
            text="Guest",
            guest_name="Guest",
            guest_email="guest@example.invalid",
        )
        url = reverse("commentail:resend", args=[comment.pk])
        self.assertEqual(self.client.post(url).status_code, 404)
        session = self.client.session
        session["commentail_own"] = [comment.pk]
        session.save()
        job = MailJob.objects.get(comment=comment, kind="confirm")
        deadline, token = job.expires_at, job.token_id
        job.status = "failed"
        job.save()
        self.assertEqual(self.client.post(url).status_code, 302)
        job.refresh_from_db()
        self.assertEqual(
            (job.status, job.expires_at, job.token_id), ("pending", deadline, token)
        )
        self.assertEqual(self.client.post(url).status_code, 400)

    def test_registered_author_without_optional_headers_is_not_suspicious(self):
        SiteCommentSettings.objects.create(site=self.site, moderation="none")
        self.client.force_login(self.user)
        key = self.client.get(self.url).context["form_key"]
        response = self.client.post(
            reverse("commentail:submit", args=[self.site.root_page.pk]),
            {"key": key, "text": "Registered"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.discussion.comments.get().status, "published")

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
        EMAIL_HOST="127.0.0.1",
    )
    def test_remembered_guest_hint_distinguishes_a_changed_email(self):
        from commentail.security import remember_guest

        self.client.cookies[f"commentail_guest_{self.site.pk}"] = remember_guest(
            self.site, "guest@example.invalid"
        )
        hint = "This email is confirmed in this browser. A different email needs confirmation."
        response = self.client.get(self.url)
        self.assertIsNone(response.context["captcha"])
        self.assertContains(response, hint)
        self.assertNotContains(
            response, "After submitting, we will email you a link to confirm your email address."
        )
        response = self.client.post(
            reverse("commentail:submit", args=[self.site.root_page.pk]),
            {"refresh": "1", "email": "another@example.invalid"},
        )
        self.assertIsNotNone(response.context["captcha"])
        self.assertNotContains(response, hint)
        self.assertContains(
            response, "After submitting, we will email you a link to confirm your email address."
        )

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
        EMAIL_HOST="127.0.0.1",
    )
    def test_guest_http_confirmation_publication_and_revision_with_csrf(self):
        from django.test import Client

        from commentail.models import CaptchaChallenge, MailJob
        from commentail.security import token_secret

        browser = Client(enforce_csrf_checks=True)
        response = browser.get(self.url)
        task = response.context["captcha"]
        data = {
            "key": response.context["form_key"],
            "text": "Guest original",
            "name": "Guest",
            "email": "guest@example.invalid",
            "challenge": str(task.id),
            "answer": str(CaptchaChallenge.objects.get(pk=task.id).answer),
        }
        submit_url = reverse("commentail:submit", args=[self.site.root_page.pk])
        self.assertEqual(browser.post(submit_url, data).status_code, 403)
        data["csrfmiddlewaretoken"] = browser.cookies["csrftoken"].value
        self.assertEqual(browser.post(submit_url, data).status_code, 302)
        comment = self.discussion.comments.get()
        self.assertEqual(comment.status, "awaiting_email")
        self.assertNotContains(self.client.get(self.url), "Guest original")
        job = MailJob.objects.get(comment=comment, kind="confirm")
        confirm_url = reverse("commentail:action", args=["confirm"])
        secret = token_secret(job.token)
        self.assertEqual(browser.get(confirm_url, {"token": secret}).status_code, 200)
        comment.refresh_from_db()
        self.assertEqual(comment.status, "awaiting_email")
        self.assertEqual(
            browser.post(
                confirm_url,
                {
                    "token": secret,
                    "csrfmiddlewaretoken": browser.cookies["csrftoken"].value,
                },
            ).status_code,
            303,
        )
        comment.refresh_from_db()
        self.assertEqual(comment.status, "pending")
        self.assertIsNone(browser.get(self.url).context["captcha"])
        moderate(comment.pk, "approve", actor=self.admin)
        edit = MailJob.objects.get(comment=comment, kind="edit")
        edit_url = reverse("commentail:action", args=["edit"])
        response = browser.post(
            edit_url,
            {
                "token": token_secret(edit.token),
                "text": "Guest revised",
                "csrfmiddlewaretoken": browser.cookies["csrftoken"].value,
            },
        )
        self.assertEqual(response.status_code, 303)
        self.assertContains(self.client.get(self.url), "Guest original")
        self.assertNotContains(self.client.get(self.url), "Guest revised")

    def test_widget_declares_its_language_independently_of_the_host_document(self):
        from html.parser import HTMLParser

        from django.utils.translation import override

        class WidgetParser(HTMLParser):
            language = None

            def handle_starttag(self, tag, attrs):
                attributes = dict(attrs)
                if tag == "section" and "data-discussion" in attributes:
                    self.language = attributes.get("lang")

        for language in ("ru", "en"):
            with self.subTest(language=language), override(language):
                parser = WidgetParser()
                parser.feed(self.client.get(self.url).content.decode())
                self.assertEqual(parser.language, language)


    def test_reading_state_retains_multiple_open_threads_and_reply_windows(self):
        from django.utils import timezone

        from commentail.public import _next

        roots = []
        children = []
        for index in range(2):
            root = submit(self.discussion.pk, text=f"Root {index}", user=self.admin)
            moderate(root.pk, "approve", actor=self.admin)
            roots.append(root)
            for number in range(22):
                child = submit(self.discussion.pk, text=f"Child {index}-{number}", user=self.admin, reply_to=root.pk)
                moderate(child.pk, "approve", actor=self.admin)
            children.append(child)
        snapshot = timezone.now().isoformat()
        navigation = {"thread": [str(root.pk) for root in roots], "replies": [_next(self.discussion, snapshot, 20, root.pk) for root in roots]}
        response = self.client.get(self.url, navigation)
        for child in children:
            self.assertContains(response, f'id="commentail-{child.pk}"')
        redirected = self.client.get(self.url, navigation, HTTP_ACCEPT="text/html")
        from urllib.parse import parse_qs, urlsplit
        query = parse_qs(urlsplit(redirected["Location"]).query)
        self.assertEqual(query["thread"], navigation["thread"])
        self.assertEqual(query["replies"], navigation["replies"])

    def test_pending_reply_target_opens_parent_only_for_its_author(self):
        root = submit(self.discussion.pk, text="Root", user=self.admin)
        moderate(root.pk, "approve", actor=self.admin)
        child = submit(self.discussion.pk, text="Child", user=self.admin, reply_to=root.pk)
        moderate(child.pk, "approve", actor=self.admin)
        pending = submit(self.discussion.pk, text="Private reply", user=self.user, reply_to=child.pk)
        self.client.force_login(self.user)
        own = self.client.get(self.url, {"target": pending.pk})
        self.assertContains(own, f'id="commentail-{child.pk}"')
        self.assertContains(own, f'data-reply-to="{child.pk}"')
        self.client.logout()
        other = self.client.get(self.url, {"target": pending.pk})
        self.assertNotContains(other, "Private reply")
        self.assertNotContains(other, f'id="commentail-{child.pk}"')


    def test_new_root_target_stays_first_without_discarding_loaded_snapshot(self):
        from django.utils import timezone

        from commentail.public import _next

        previous = submit(self.discussion.pk, text="Previous", user=self.admin)
        moderate(previous.pk, "approve", actor=self.admin)
        window = _next(self.discussion, timezone.now().isoformat(), 0)
        latest = submit(self.discussion.pk, text="New main comment", user=self.admin)
        moderate(latest.pk, "approve", actor=self.admin)
        response = self.client.get(self.url, {"window": window, "target": latest.pk})
        self.assertEqual([row["id"] for row in response.context["rows"]], [latest.pk, previous.pk])

    def test_target_reply_after_snapshot_is_rendered_and_new_root_stays_first(self):
        from django.utils import timezone

        from commentail.public import _next

        previous = submit(self.discussion.pk, text="Previous root", user=self.admin)
        moderate(previous.pk, "approve", actor=self.admin)
        window = _next(self.discussion, timezone.now().isoformat(), 0)
        latest = submit(self.discussion.pk, text="Root after snapshot", user=self.admin)
        moderate(latest.pk, "approve", actor=self.admin)
        reply = submit(self.discussion.pk, text="Targeted fresh reply", user=self.admin, reply_to=latest.pk)
        moderate(reply.pk, "approve", actor=self.admin)
        other = submit(self.discussion.pk, text="Unrequested fresh reply", user=self.admin, reply_to=latest.pk)
        moderate(other.pk, "approve", actor=self.admin)

        response = self.client.get(self.url, {"window": window, "target": reply.pk})
        self.assertContains(response, f'id="commentail-{reply.pk}"')
        self.assertNotContains(response, f'id="commentail-{other.pk}"')
        self.assertEqual([row["id"] for row in response.context["rows"]], [latest.pk, previous.pk])
        self.assertEqual(response.context["rows"][0]["reply_count"], 1)
