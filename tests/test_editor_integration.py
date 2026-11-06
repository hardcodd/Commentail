"""Admission and legacy compatibility through the actual domain services."""

from datetime import timedelta
from urllib.parse import urlsplit

from bs4 import BeautifulSoup
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from wagtail.models import Site

from commentail.editor import settings_for
from commentail.models import (
    CaptchaChallenge,
    Comment,
    Discussion,
    RateEvent,
    SiteCommentSettings,
)
from commentail.outbox import process_mail
from commentail.policies import editorial_settings
from commentail.services import DomainError, moderate, moderate_revision, revise, submit


class EditorIntegrationTests(TestCase):
    def setUp(self):
        self.site = Site.objects.get(is_default_site=True)
        self.discussion = Discussion.objects.create(
            site=self.site, page=self.site.root_page
        )
        self.author = get_user_model().objects.create_user("writer")
        self.admin = get_user_model().objects.create_superuser(
            "admin", "admin@example.invalid", "synthetic"
        )
        self.options = SiteCommentSettings.objects.create(
            site=self.site, moderation="none"
        )

    def test_default_is_literal_and_cannot_be_overridden_by_source(self):
        comment = submit(self.discussion.pk, text="**literal**", user=self.author)
        self.assertEqual(comment.text_format, "plain")

    def test_registered_and_guest_modes_are_independent(self):
        self.options.registered_editor = "visual"
        self.options.save()
        comment = submit(self.discussion.pk, text="**bold**", user=self.author)
        self.assertEqual(comment.text_format, "markdown")
        guest = submit(
            self.discussion.pk,
            text="**literal**",
            guest_name="Guest",
            guest_email="g@example.invalid",
        )
        self.assertEqual(guest.text_format, "plain")

    def test_disabled_format_is_rejected_in_nested_markdown(self):
        self.options.registered_editor = "markdown"
        self.options.editor_features = ["quote", "italic"]
        self.options.save()
        with self.assertRaises(DomainError):
            submit(self.discussion.pk, text="> *x **forbidden***", user=self.author)
        self.assertFalse(Comment.objects.exists())

    def test_legacy_revision_remains_plain(self):
        comment = submit(self.discussion.pk, text="**literal**", user=self.author)
        self.options.registered_editor = "visual"
        self.options.save()
        revise(comment.pk, "**still literal**", user=self.author)
        comment.refresh_from_db()
        self.assertEqual(comment.text_format, "plain")

    def test_moderated_revision_keeps_format(self):
        self.options.registered_editor = "visual"
        self.options.save()
        comment = submit(self.discussion.pk, text="**first**", user=self.author)
        self.options.moderation = "all"
        self.options.save()
        revision = revise(comment.pk, "*second*", user=self.author)
        self.assertEqual(revision.text_format, "markdown")
        moderate_revision(revision.pk, "approve", actor=self.admin)
        comment.refresh_from_db()
        self.assertEqual((comment.text, comment.text_format), ("*second*", "markdown"))

    def test_mode_change_does_not_reinterpret_stored_markdown(self):
        self.options.registered_editor = "visual"
        self.options.save()
        comment = submit(self.discussion.pk, text="**first**", user=self.author)
        self.options.registered_editor = "plain"
        self.options.save()
        policy = settings_for(
            editorial_settings(self.discussion),
            guest=False,
            text_format=comment.text_format,
        )
        self.assertEqual(policy["registered"], "markdown")
        self.assertEqual(policy["features"], [])
        with self.assertRaises(DomainError):
            revise(comment.pk, "**new bold**", user=self.author)
        revise(comment.pk, "plain replacement", user=self.author)
        comment.refresh_from_db()
        self.assertEqual(comment.text_format, "markdown")

    def test_direct_post_cannot_forge_plain_format_to_bypass_policy(self):
        self.options.registered_editor = "visual"
        self.options.editor_features = []
        self.options.save()
        self.client.force_login(self.author)
        form = self.client.get(
            reverse("commentail:discussion", args=[self.site.root_page.pk])
        )
        response = self.client.post(
            reverse("commentail:submit", args=[self.site.root_page.pk]),
            {
                "key": form.context["form_key"],
                "text": "**forbidden**",
                "text_format": "plain",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Comment.objects.exists())
        self.assertEqual(
            BeautifulSoup(response.content, "html.parser")
            .select_one('textarea[name="text"]')
            .text,
            "**forbidden**",
        )

    def test_modes_do_not_change_published_markup_or_legacy_literals(self):
        self.options.registered_editor = "visual"
        self.options.save()
        rich = submit(
            self.discussion.pk, text="**bold** <script>x</script>", user=self.author
        )
        legacy = Comment.objects.create(
            discussion=self.discussion,
            user=self.author,
            text="**literal**",
            status="published",
            published_at=rich.published_at,
        )
        self.options.registered_editor = "plain"
        self.options.editor_features = []
        self.options.save()
        markup = BeautifulSoup(
            self.client.get(
                reverse("commentail:discussion", args=[self.site.root_page.pk])
            ).content,
            "html.parser",
        )
        self.assertEqual(
            markup.select_one(f"#commentail-{rich.pk} strong").text, "writer"
        )
        self.assertEqual(
            markup.select_one(f"#commentail-{rich.pk} .commentail-text strong").text,
            "bold",
        )
        self.assertIsNone(markup.select_one(f"#commentail-{rich.pk} script"))
        self.assertEqual(
            markup.select_one(f"#commentail-{legacy.pk} .commentail-text").text,
            "**literal**",
        )

    def test_each_capability_is_enforced_on_the_server(self):
        from commentail.markdown import FEATURES

        examples = dict(
            zip(
                FEATURES,
                [
                    "**x**",
                    "*x*",
                    "~~x~~",
                    "[x](https://example.com)",
                    "> x",
                    "- x",
                    "1. x",
                    "`x`",
                    "```\nx\n```",
                ],
            )
        )
        for feature, source in examples.items():
            with self.subTest(feature=feature):
                self.options.registered_editor = "markdown"
                self.options.editor_features = [
                    name for name in FEATURES if name != feature
                ]
                self.options.save()
                with self.assertRaises(DomainError):
                    submit(self.discussion.pk, text=source, user=self.author)
        self.assertFalse(Comment.objects.exists())

    def test_empty_markdown_containers_are_rejected(self):
        self.options.registered_editor = "markdown"
        self.options.save()
        for source in ("> ", "```\n```", "- ", "1. "):
            with self.subTest(source=source), self.assertRaises(DomainError):
                submit(self.discussion.pk, text=source, user=self.author)

    def test_second_site_has_independent_modes_and_features(self):
        other = Site.objects.create(
            hostname="other.invalid", root_page=self.site.root_page
        )
        SiteCommentSettings.objects.create(
            site=other, registered_editor="markdown", editor_features=["italic"]
        )
        discussion = Discussion.objects.create(site=other, page=self.site.root_page)
        self.assertEqual(
            submit(
                self.discussion.pk, text="**literal**", user=self.author
            ).text_format,
            "plain",
        )
        self.assertEqual(
            submit(discussion.pk, text="*allowed*", user=self.author).text_format,
            "markdown",
        )
        with self.assertRaises(DomainError):
            submit(discussion.pk, text="**forbidden**", user=self.author)

    def test_toolbar_precedes_both_fields_in_create_reply_and_edit_forms(self):
        self.options.registered_editor = "visual"
        self.options.save()
        comment = submit(self.discussion.pk, text="**original**", user=self.author)
        other_comment = submit(self.discussion.pk, text="Other author", user=self.admin)
        self.client.force_login(self.author)
        url = reverse("commentail:discussion", args=[self.site.root_page.pk])
        selectors = (
            ({}, ".commentail-form"),
            ({"reply_to": other_comment.pk}, ".commentail-form[data-reply-to]"),
            ({"edit_comment": comment.pk}, ".commentail-edit-form"),
        )
        for query, selector in selectors:
            with self.subTest(form=selector):
                markup = BeautifulSoup(
                    self.client.get(url, query).content, "html.parser"
                )
                form = markup.select_one(selector)
                self.assertIsNotNone(form)
                rich = form.select_one(".commentail-rich")
                toolbar = rich.select_one(".editor-topbar")
                source = rich.select_one("textarea")
                self.assertEqual(source.get("autocomplete"), "off")
                visual = rich.select_one("[data-editor-root]")
                nodes = list(rich.descendants)
                self.assertLess(nodes.index(toolbar), nodes.index(source))
                self.assertLess(nodes.index(toolbar), nodes.index(visual))
                label = rich.select_one(f'label[for="{source["id"]}"]')
                self.assertIsNotNone(label)
                self.assertIsNone(toolbar.find_parent("label"))
                length = rich.select_one(".commentail-length")
                self.assertIsNotNone(length)
                self.assertEqual(visual.find_next_sibling()["class"], length["class"])
                self.assertIn(length["id"], source["aria-describedby"].split())

    def test_runtime_locale_asset_matches_active_language(self):
        from django.utils import translation

        from commentail.assets import editor_locale_url

        self.options.guest_editor = "visual"
        self.options.save()
        url = reverse("commentail:discussion", args=[self.site.root_page.pk])
        for language, asset in [
            ("en", ""),
            ("ru", "editor-ru.js"),
            ("de-at", "editor-de.js"),
            ("fr", "editor-fr.js"),
            ("es", "editor-es.js"),
            ("pt-br", "editor-pt-br.js"),
            ("xx", ""),
        ]:
            with self.subTest(language=language), translation.override(language):
                markup = BeautifulSoup(self.client.get(url).content, "html.parser")
                value = markup.select_one("[data-editor-locale]")["data-editor-locale"]
                self.assertEqual(value, editor_locale_url(language))
                if asset:
                    self.assertIn(asset + "?v=", value)
                else:
                    self.assertEqual(value, "")

    @override_settings(COMMENTAIL={"default": {"GUEST_FORM_MIN_SECONDS": 0}})
    def test_full_guest_editor_confirmation_publication_and_revision_with_csrf(self):
        """Actual forms, CAPTCHA backend, outbox and emailed capabilities in all modes."""
        url = reverse("commentail:discussion", args=[self.site.root_page.pk])

        def fields(response, selector):
            form = BeautifulSoup(response.content, "html.parser").select_one(selector)
            self.assertIsNotNone(form)
            return form, {
                node["name"]: node.get("value", "")
                for node in form.select('input[type="hidden"][name]')
            }

        def emailed_action(purpose):
            links = [
                link["href"]
                for message in mail.outbox
                for link in BeautifulSoup(
                    message.alternatives[0][0], "html.parser"
                ).select("a[href]")
                if f"/actions/{purpose}/?" in link["href"]
            ]
            self.assertTrue(links, purpose)
            return links[-1]

        for mode in ("plain", "markdown", "visual"):
            for moderation in ("none", "all"):
                with self.subTest(mode=mode, moderation=moderation):
                    mail.outbox = []
                    self.options.guest_editor = mode
                    self.options.moderation = moderation
                    self.options.save()
                    browser = Client(
                        enforce_csrf_checks=True,
                        HTTP_USER_AGENT="Synthetic guest browser",
                    )
                    source = (
                        f"Guest {mode} {moderation}: **bold** ~~old~~ `**literal**`"
                    )
                    form, data = fields(browser.get(url), ".commentail-form")
                    self.assertEqual(
                        bool(form.select_one("[data-editor-toolbar]")), mode == "visual"
                    )
                    data.update(
                        text=source,
                        name="Synthetic guest",
                        email=f"{mode}-{moderation}@example.invalid",
                    )
                    data["answer"] = str(
                        CaptchaChallenge.objects.get(pk=data["challenge"]).answer
                    )
                    response = browser.post(form["action"], data)
                    self.assertEqual(response.status_code, 302)
                    comment = Comment.objects.get(email=data["email"])
                    self.assertEqual(comment.status, "awaiting_email")
                    self.assertEqual(
                        comment.text_format, "plain" if mode == "plain" else "markdown"
                    )
                    public = Client().get(url)
                    self.assertNotContains(public, f'id="commentail-{comment.pk}"')
                    self.assertEqual(process_mail(), 1)
                    self.assertEqual(mail.outbox[0].to, [data["email"]])
                    confirmation = browser.get(emailed_action("confirm"))
                    _confirm_form, confirm_data = fields(confirmation, "form")
                    comment.refresh_from_db()
                    self.assertEqual(comment.status, "awaiting_email")  # GET is inert.
                    confirm_url = urlsplit(emailed_action("confirm")).path
                    confirmed = browser.post(confirm_url, confirm_data)
                    self.assertEqual(confirmed.status_code, 303)
                    self.assertNotIn("token=", confirmed["Location"])
                    self.assertIn(f"commentail_guest_{self.site.pk}", browser.cookies)
                    comment.refresh_from_db()
                    self.assertEqual(
                        comment.status,
                        "published" if moderation == "none" else "pending",
                    )
                    if moderation == "all":
                        self.assertNotContains(
                            Client().get(url), f'id="commentail-{comment.pk}"'
                        )
                        moderate(comment.pk, "approve", actor=self.admin)
                    process_mail()
                    public = BeautifulSoup(Client().get(url).content, "html.parser")
                    body = public.select_one(
                        f"#commentail-{comment.pk} .commentail-text"
                    )
                    self.assertIsNotNone(body)
                    self.assertEqual(bool(body.select_one("del")), mode != "plain")
                    self.assertEqual(bool(body.select_one("strong")), mode != "plain")
                    if mode != "plain":
                        self.assertEqual(body.select_one("code").text, "**literal**")
                    self.assertNotIn(data["email"], str(public))
                    edit = browser.get(emailed_action("edit"))
                    self.assertEqual(edit.status_code, 303)
                    self.assertNotIn("token=", edit["Location"])
                    edit_form, edit_data = fields(
                        browser.get(edit["Location"]), ".commentail-edit-form"
                    )
                    self.assertEqual(edit_form.select_one("textarea").text, source)
                    self.assertEqual(
                        Client()
                        .post(edit_form["action"], {"text": "Forged"})
                        .status_code,
                        404,
                    )
                    revised = source + " revised"
                    edit_data.update(text=revised, edit_comment=comment.pk)
                    edited = browser.post(edit_form["action"], edit_data)
                    self.assertEqual(edited.status_code, 303)
                    revision = comment.revisions.get()
                    self.assertEqual(revision.text_format, comment.text_format)
                    if moderation == "all":
                        self.assertEqual(revision.status, "pending")
                        moderate_revision(revision.pk, "approve", actor=self.admin)
                    comment.refresh_from_db()
                    self.assertEqual(comment.text, revised)
                    self.assertEqual(
                        comment.text_format, "plain" if mode == "plain" else "markdown"
                    )
                    # Remembered proof removes only the repeated email/CAPTCHA step.
                    RateEvent.objects.update(
                        created_at=timezone.now() - timedelta(minutes=1)
                    )
                    parent = moderate(
                        submit(self.discussion.pk, text="Another author", user=self.author).pk,
                        "approve", actor=self.admin,
                    )
                    reply_form, reply_data = fields(
                        browser.get(url, {"reply_to": parent.pk}),
                        ".commentail-form[data-reply-to]",
                    )
                    self.assertNotIn("challenge", reply_data)
                    reply_data.update(
                        text=f"Reply {mode} {moderation}",
                        name="Synthetic guest",
                        email=data["email"],
                    )
                    reply = browser.post(reply_form["action"], reply_data)
                    self.assertEqual(reply.status_code, 302)
                    child = Comment.objects.get(reply_to=parent)
                    self.assertIsNotNone(child.email_confirmed_at)
                    self.assertNotEqual(child.status, "awaiting_email")
                    process_mail()

    @override_settings(COMMENTAIL={"default": {"GUEST_FORM_MIN_SECONDS": 0}})
    def test_guest_captcha_and_disabled_strike_failures_keep_the_markdown_draft(self):
        self.options.guest_editor = "visual"
        self.options.editor_features = ["bold"]
        self.options.save()
        browser = Client(HTTP_USER_AGENT="Synthetic guest browser")
        url = reverse("commentail:discussion", args=[self.site.root_page.pk])
        for answer in ("incorrect", None):
            response = browser.get(url)
            challenge = response.context["captcha"]
            data = {
                "key": response.context["form_key"],
                "text": "~~disabled~~",
                "name": "Synthetic guest",
                "email": "failure@example.invalid",
                "challenge": str(challenge.id),
                "answer": answer
                if answer is not None
                else str(CaptchaChallenge.objects.get(pk=challenge.id).answer),
            }
            failed = browser.post(
                reverse("commentail:submit", args=[self.site.root_page.pk]), data
            )
            self.assertEqual(failed.status_code, 400)
            markup = BeautifulSoup(failed.content, "html.parser")
            self.assertEqual(
                markup.select_one('textarea[name="text"]').text, data["text"]
            )
            self.assertFalse(Comment.objects.exists())
