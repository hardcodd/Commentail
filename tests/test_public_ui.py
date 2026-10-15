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
        response = self.client.get(self.url)
        key = response.context["form_key"]
        response = self.client.post(
            reverse("commentail:submit", args=[self.site.root_page.pk]),
            {"key": key, "text": "A plain comment"},
            HTTP_USER_AGENT="Synthetic browser",
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.discussion.comments.count(), 1)

        response = self.client.post(
            reverse("commentail:submit", args=[self.site.root_page.pk]),
            {"key": key, "text": "A plain comment"},
            HTTP_USER_AGENT="Synthetic browser",
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.discussion.comments.count(), 1)

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
        response = self.client.get(edit)
        self.assertNotContains(response, 'name="text"')
        self.assertEqual(response.headers["Cache-Control"], "private, no-store")
        self.discussion.mode = "open"
        self.discussion.save()
        comment.edit_locked = True
        comment.save()
        self.assertNotContains(self.client.get(edit), 'name="text"')

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
            response, "Confirm your email before moderation and publication."
        )
        response = self.client.post(
            reverse("commentail:submit", args=[self.site.root_page.pk]),
            {"refresh": "1", "email": "another@example.invalid"},
        )
        self.assertIsNotNone(response.context["captcha"])
        self.assertNotContains(response, hint)
        self.assertContains(
            response, "Confirm your email before moderation and publication."
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
            200,
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
        self.assertEqual(response.status_code, 200)
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
