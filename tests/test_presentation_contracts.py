"""Compatibility checks for host templates using the accepted public fields."""

from datetime import datetime, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.template import Context, Template
from django.template.loader import render_to_string
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import override
from wagtail.models import Site

from commentail.models import Discussion, MailJob, SiteCommentSettings
from commentail.outbox import deliver
from commentail.security import issue_token
from commentail.services import moderate, submit


class PresentationContractTests(TestCase):
    def setUp(self):
        self.site = Site.objects.get(is_default_site=True)
        self.discussion = Discussion.objects.create(
            site=self.site, page=self.site.root_page
        )
        self.author = get_user_model().objects.create_user("contract-author")
        self.admin = get_user_model().objects.create_superuser(
            "contract-admin", "", "test"
        )
        self.url = reverse("commentail:discussion", args=[self.site.root_page.pk])

    def test_guest_name_label_uses_unambiguous_translation_key(self):
        request = RequestFactory().get("/")
        request.user = AnonymousUser()
        for language, label in (("en", "Name"), ("ru", "Имя")):
            with self.subTest(language=language), override(language):
                html = render_to_string(
                    "commentail/form.html", {"request": request, "remembered_email": ""}
                )
                self.assertIn(label + "<input", html)
                self.assertIn('data-commentail-name-limit="40"', html)
                self.assertIn("40", html)

    def test_widget_fields_remain_available_in_open_read_only_and_hidden_modes(self):
        settings = SiteCommentSettings.objects.create(site=self.site)
        common = {
            "language_code",
            "discussion_id",
            "page_id",
            "options",
            "hidden",
            "entered_text",
            "entered_name",
            "entered_email",
            "error",
            "editing",
        }
        visible = {
            "window_token",
            "rows",
            "own",
            "count",
            "more_url",
            "can_post",
            "form_key",
            "main_form_key",
            "captcha",
            "remembered_email",
            "guest_email_confirmed",
            "reply_to",
            "cancel_reply_url",
            "submit_url",
            "structured_microdata",
            "structured_comments",
        }
        self.client.force_login(self.author)
        for mode in ("open", "read_only", "hidden"):
            with self.subTest(mode=mode):
                settings.mode = mode
                settings.save()
                response = self.client.get(self.url)
                self.assertEqual(response.status_code, 200)
                for field in common | (visible if mode != "hidden" else set()):
                    self.assertIn(field, response.context)
                self.assertEqual(response.context["options"].mode, mode)
                self.assertEqual(response.context["hidden"], mode == "hidden")
                for field in (
                    "moderation",
                    "access",
                    "max_length",
                    "clickable_links",
                    "notify_publication",
                    "notify_rejection",
                ):
                    self.assertTrue(hasattr(response.context["options"], field), field)
                if mode != "hidden":
                    self.assertEqual(response.context["can_post"], mode == "open")
                    for field in ("rows", "own", "structured_comments"):
                        self.assertIsInstance(response.context[field], list)
                    for field in (
                        "window_token",
                        "more_url",
                        "form_key",
                        "main_form_key",
                        "remembered_email",
                        "cancel_reply_url",
                        "submit_url",
                    ):
                        self.assertIsInstance(response.context[field], str)
                else:
                    self.assertNotContains(response, "<form")

    def test_root_and_reply_cards_preserve_fields_without_exposing_internal_models(
        self,
    ):
        root = moderate(
            submit(self.discussion.pk, text="Root", user=self.author).pk,
            "approve",
            actor=self.admin,
        )
        reply = moderate(
            submit(
                self.discussion.pk, text="Reply", user=self.author, reply_to=root.pk
            ).pk,
            "approve",
            actor=self.admin,
        )
        fields = {
            "id",
            "display_name",
            "initials",
            "gradient",
            "avatar_url",
            "body",
            "published_at",
            "edited_at",
            "status",
            "status_label",
            "reason",
            "resend_url",
            "edit_url",
            "reply_to_id",
            "reply_to_name",
            "permalink",
            "reply_url",
            "schema",
        }
        closed = self.client.get(self.url).context["rows"][0]
        self.assertFalse(closed["opened"])
        self.assertNotIn("replies", closed)
        opened = self.client.get(self.url, {"target": reply.pk}).context["rows"][0]
        self.assertTrue(opened["opened"])
        self.assertTrue(
            {
                "reply_count",
                "opened",
                "reply_window",
                "expand_url",
                "more_replies",
                "replies",
            }
            <= opened.keys()
        )
        child = opened["replies"][0]
        for card in (opened, child):
            self.assertIsInstance(card, dict)
            self.assertTrue(fields <= card.keys())
            self.assertTrue(timezone.is_aware(card["published_at"]))
            self.assertFalse({"user", "email", "discussion", "text"} & card.keys())
        self.assertNotIn("replies", child)
        self.assertEqual(child["reply_to_id"], root.pk)

    def test_action_contexts_keep_normal_fields_and_neutral_failure_boundary(self):
        comment = submit(
            self.discussion.pk,
            text="Private action body",
            guest_name="Guest",
            guest_email="guest@example.invalid",
        )
        normal = {
            "language_code",
            "page_title",
            "return_url",
            "purpose",
            "token",
            "message",
            "error",
            "text",
            "status_label",
            "reason",
        }
        for purpose in ("confirm", "view", "unsubscribe"):
            with self.subTest(purpose=purpose):
                secret = issue_token(
                    comment, purpose, timezone.now() + timedelta(hours=1)
                )
                url = reverse("commentail:action", args=[purpose])
                response = self.client.get(url, {"token": secret})
                self.assertEqual(response.status_code, 200)
                for field in normal:
                    self.assertIn(field, response.context)
                self.assertEqual(response.context["purpose"], purpose)
                self.assertEqual(
                    response.context["text"], comment.text if purpose == "view" else ""
                )
                failure = self.client.get(url, {"token": "invalid"})
                self.assertEqual(failure.status_code, 404)
                self.assertTrue(failure.context["unavailable"])
                self.assertEqual(failure.context["return_url"], "/")
                for field in (
                    "purpose",
                    "token",
                    "message",
                    "text",
                    "status_label",
                    "reason",
                ):
                    self.assertNotIn(field, failure.context)

    @override_settings(ROOT_URLCONF="tests.urls_custom_prefix")
    def test_all_mail_families_keep_metadata_only_context_and_absolute_custom_urls(
        self,
    ):
        comment = submit(
            self.discussion.pk,
            text="Private email body",
            guest_name="Guest",
            guest_email="guest@example.invalid",
        )
        job = MailJob.objects.get(kind="confirm")
        expected = {
            "kind",
            "author_name",
            "site_name",
            "site_url",
            "target_url",
            "action_url",
            "view_url",
            "reason",
            "is_revision",
            "expires_at",
        }
        captures = []

        def capture(name, context):
            captures.append(dict(context))
            return render_to_string(name, context)

        with patch("commentail.outbox.render_to_string", side_effect=capture):
            for kind in ("confirm", "edit", "published", "rejected", "reply"):
                with self.subTest(kind=kind):
                    job.kind = kind
                    deliver(job)
                    context = captures[-1]
                    self.assertEqual(set(context), expected)
                    self.assertEqual(context["kind"], kind)
                    self.assertIsInstance(context["expires_at"], datetime)
                    self.assertTrue(timezone.is_aware(context["expires_at"]))
                    self.assertIsInstance(context["is_revision"], bool)
                    for field in expected - {"expires_at", "is_revision"}:
                        self.assertIsInstance(context[field], str)
                    for field in ("site_url", "target_url", "action_url", "view_url"):
                        if context[field]:
                            self.assertRegex(context[field], r"^https?://")
                    self.assertIn("/community/feedback/actions/", context["action_url"])
                    self.assertNotIn(comment.text, str(context))
                    self.assertNotIn(comment.email, str(context))

    @override_settings(STATIC_URL="https://cdn.example.invalid/assets/")
    def test_resource_tags_render_usable_host_static_urls(self):
        from bs4 import BeautifulSoup

        from commentail.assets import asset_url

        asset_url.cache_clear()
        try:
            html = Template(
                "{% load commentail_tags %}{% commentail_css %}{% commentail_js %}"
                "{% commentail_asset 'commentail.css' as css %}<a id='css' href='{{ css }}'></a>"
                "{% commentail_asset 'commentail.js' as js %}<a id='js' href='{{ js }}'></a>"
                "{% commentail_asset 'admin.css' as admin_css %}<a id='admin-css' href='{{ admin_css }}'></a>"
                "{% commentail_asset 'admin.js' as admin_js %}<a id='admin-js' href='{{ admin_js }}'></a>"
            ).render(Context())
            document = BeautifulSoup(html, "html.parser")
            self.assertEqual(
                document.select_one("link[rel=stylesheet]")["href"],
                document.select_one("#css")["href"],
            )
            script = document.select_one("script")
            self.assertTrue(script.has_attr("defer"))
            self.assertEqual(script["src"], document.select_one("#js")["href"])
            for identifier, name in (
                ("css", "commentail.css"),
                ("js", "commentail.js"),
                ("admin-css", "admin.css"),
                ("admin-js", "admin.js"),
            ):
                self.assertTrue(
                    document.select_one("#" + identifier)["href"].startswith(
                        "https://cdn.example.invalid/assets/commentail/" + name
                    )
                )
        finally:
            asset_url.cache_clear()
