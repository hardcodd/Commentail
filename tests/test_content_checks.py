from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from wagtail.models import Locale, Page, Site

from commentail.models import Comment, Discussion, ModerationRule, Policy, RateEvent
from commentail.security import issue_token
from commentail.services import (
    DomainError,
    confirm_email,
    revise,
    submit,
    submit_once,
)

LONG_TEXT = (
    "A useful, detailed explanation of the topic with enough context for other readers. "
    * 2
)
LINKS = "References: https://one.invalid/a https://two.invalid/b WWW.three.invalid/c"


class ContentCheckTests(TestCase):
    def setUp(self):
        self.site = Site.objects.get(is_default_site=True)
        self.discussion = Discussion.objects.create(
            site=self.site, page=self.site.root_page, moderation=Policy.NONE
        )

    def guest(self, text, **kwargs):
        return submit(
            kwargs.pop("discussion_id", self.discussion.pk),
            text=text,
            guest_name="Guest",
            guest_email=kwargs.pop("guest_email", "guest@example.invalid"),
            **kwargs,
        )

    def test_long_repeated_text_is_reviewed_after_email_confirmation(self):
        first = self.guest(LONG_TEXT)
        second = self.guest("\n" + LONG_TEXT.upper().replace(" ", "  "))
        self.assertFalse(first.suspicious)
        self.assertIn("duplicate_text", second.spam_signals)
        self.assertEqual(second.text, "\n" + LONG_TEXT.upper().replace(" ", "  "))
        self.assertEqual(confirm_email(first.pk).status, Comment.Status.PUBLISHED)
        self.assertEqual(confirm_email(second.pk).status, Comment.Status.PENDING)

    def test_short_common_replies_are_not_duplicates(self):
        self.guest("Thank you!")
        second = self.guest("Thank you!")
        self.assertFalse(second.suspicious)
        self.assertFalse(RateEvent.objects.filter(kind="content").exists())

    def test_duplicate_scope_is_site_wide_not_email_or_discussion(self):
        self.guest(LONG_TEXT)
        page = self.site.root_page.add_child(instance=Page(title="Other", slug="other"))
        other = Discussion.objects.create(site=self.site, page=page)
        second = self.guest(
            LONG_TEXT, discussion_id=other.pk, guest_email="other@example.invalid"
        )
        self.assertIn("duplicate_text", second.spam_signals)
        site = Site.objects.create(
            hostname="other.invalid", root_page=self.site.root_page
        )
        independent = Discussion.objects.create(site=site, page=self.site.root_page)
        self.assertFalse(self.guest(LONG_TEXT, discussion_id=independent.pk).suspicious)

    def test_expired_text_and_format_characters(self):
        self.guest(LONG_TEXT)
        second = self.guest(LONG_TEXT.replace("topic", "to\u200bpic"))
        self.assertIn("duplicate_text", second.spam_signals)
        RateEvent.objects.filter(kind="content").update(
            created_at=timezone.now() - timedelta(hours=2)
        )
        self.assertFalse(self.guest(LONG_TEXT).suspicious)

    def test_unicode_normalization_and_minimum_length_boundary(self):
        self.guest(LONG_TEXT)
        self.assertIn(
            "duplicate_text", self.guest(LONG_TEXT.replace("A", "Ａ")).spam_signals
        )
        self.guest("x" * 79)
        self.assertFalse(self.guest("x" * 79).suspicious)
        self.guest("x" * 80)
        self.assertIn("duplicate_text", self.guest("x" * 80).spam_signals)

    def test_links_are_signals_not_rejections_or_network_requests(self):
        for text, expected in (
            ("See https://one.invalid/a", False),
            ("https://one.invalid/a and www.two.invalid/b", False),
            (LINKS, True),
        ):
            with self.subTest(text=text):
                comment = self.guest(text)
                self.assertEqual("many_links" in comment.spam_signals, expected)
                self.assertEqual(comment.text, text)
                self.assertEqual(
                    confirm_email(comment.pk).status,
                    Comment.Status.PENDING if expected else Comment.Status.PUBLISHED,
                )

    @override_settings(
        COMMENTAIL={
            "default": {
                "GUEST_DUPLICATE_WINDOW_SECONDS": 0,
                "GUEST_LINK_REVIEW_THRESHOLD": 0,
            }
        }
    )
    def test_checks_can_be_disabled_without_storing_fingerprints(self):
        self.guest(LONG_TEXT + LINKS)
        self.assertFalse(self.guest(LONG_TEXT + LINKS).suspicious)
        self.assertFalse(RateEvent.objects.filter(kind="content").exists())

    def test_invalid_submissions_and_idempotent_retries_do_not_add_fingerprints(self):
        with self.assertRaises(DomainError):
            self.guest(LONG_TEXT, guest_email="invalid")
        self.assertFalse(RateEvent.objects.filter(kind="content").exists())
        values = {
            "text": LONG_TEXT,
            "guest_name": "Guest",
            "guest_email": "guest@example.invalid",
        }
        first = submit_once(self.discussion.pk, "stable-key", **values)
        second = submit_once(self.discussion.pk, "stable-key", **values)
        self.assertEqual(first.pk, second.pk)
        self.assertFalse(second.suspicious)
        self.assertEqual(RateEvent.objects.filter(kind="content").count(), 1)

    def test_registered_authors_keep_existing_policy(self):
        user = get_user_model().objects.create_user("writer")
        for _ in range(2):
            comment = submit(self.discussion.pk, text=LONG_TEXT + LINKS, user=user)
            self.assertEqual(comment.status, Comment.Status.PUBLISHED)
        self.assertFalse(RateEvent.objects.filter(kind="content").exists())

    def test_guest_revision_cannot_bypass_link_check(self):
        original = confirm_email(self.guest("Original text").pk)
        token = issue_token(original, "edit", timezone.now() + timedelta(minutes=10))
        revision = revise(original.pk, LINKS, edit_token=token, site=self.site)
        self.assertEqual(revision.status, "pending")
        self.assertIn("many_links", revision.spam_signals)
        original.refresh_from_db()
        self.assertEqual(original.text, "Original text")
        self.assertFalse(original.suspicious)

    def test_unchanged_guest_revision_does_not_duplicate_its_own_text(self):
        original = confirm_email(self.guest(LONG_TEXT).pk)
        token = issue_token(original, "edit", timezone.now() + timedelta(minutes=10))
        revision = revise(original.pk, LONG_TEXT, edit_token=token, site=self.site)
        self.assertEqual(revision.status, "approved")
        self.assertEqual(revision.spam_signals, [])
        self.assertEqual(RateEvent.objects.filter(kind="content").count(), 1)

    def test_normalized_equal_revision_still_checks_newly_active_links(self):
        original = confirm_email(self.guest(LINKS.replace("https", "ｈttps")).pk)
        self.assertEqual(original.status, Comment.Status.PUBLISHED)
        token = issue_token(original, "edit", timezone.now() + timedelta(minutes=10))
        revision = revise(original.pk, LINKS, edit_token=token, site=self.site)
        self.assertEqual(revision.status, "pending")
        self.assertEqual(revision.spam_signals, ["many_links"])

    def test_approved_link_revision_is_not_flagged_again_when_unchanged(self):
        from commentail.services import moderate_revision

        original = confirm_email(self.guest("Original text").pk)
        token = issue_token(original, "edit", timezone.now() + timedelta(minutes=10))
        revision = revise(original.pk, LINKS, edit_token=token, site=self.site)
        admin = get_user_model().objects.create_superuser(
            "admin", "admin@example.invalid", "synthetic"
        )
        moderate_revision(revision.pk, "approve", actor=admin)
        unchanged = revise(original.pk, LINKS, edit_token=token, site=self.site)
        self.assertEqual(unchanged.status, "approved")
        self.assertEqual(unchanged.spam_signals, [])

    def test_explicit_reject_rules_still_win(self):
        self.discussion.moderation = Policy.RULES
        self.discussion.save()
        ModerationRule.objects.create(phrase="References", action="reject")
        with self.assertRaisesMessage(DomainError, "Text does not comply"):
            self.guest(LINKS)
        self.assertFalse(Comment.objects.exists())

    def test_settings_validation_and_hostname_overrides(self):
        from commentail.config import configuration_errors

        for name, value in (
            ("GUEST_DUPLICATE_MIN_LENGTH", 0),
            ("GUEST_DUPLICATE_WINDOW_SECONDS", -1),
            ("GUEST_LINK_REVIEW_THRESHOLD", True),
        ):
            with (
                self.subTest(name=name),
                override_settings(COMMENTAIL={"default": {name: value}}),
            ):
                self.assertTrue(configuration_errors())
        with override_settings(
            COMMENTAIL={self.site.hostname: {"GUEST_LINK_REVIEW_THRESHOLD": 1}}
        ):
            self.assertIn(
                "many_links", self.guest("See https://one.invalid").spam_signals
            )

    def test_revision_signals_are_visible_only_to_moderators(self):
        from commentail.admin_views import detail

        original = confirm_email(self.guest("Original").pk)
        token = issue_token(original, "edit", timezone.now() + timedelta(minutes=10))
        revise(original.pk, LINKS, edit_token=token, site=self.site)
        request = RequestFactory().get("/")
        request.user = get_user_model().objects.create_superuser(
            "admin", "admin@example.invalid", "synthetic"
        )
        response = detail(request, original.pk)
        self.assertIn(
            "The link count reached the review threshold.",
            response.render().content.decode(),
        )
        public = self.client.get(
            reverse("commentail:discussion", args=[self.site.root_page.pk])
        )
        self.assertNotContains(public, "The link count reached the review threshold.")

    def test_public_admission_preserves_content_and_form_signals(self):
        from django.contrib.auth.models import AnonymousUser
        from django.contrib.sessions.backends.db import SessionStore

        from commentail.admission import accept_request, issue_form
        from commentail.security import remember_guest

        request = RequestFactory().post(
            "/", REMOTE_ADDR="127.0.0.1", HTTP_USER_AGENT="Browser"
        )
        request.user = AnonymousUser()
        request.session = SessionStore()
        request.session.create()
        request.COOKIES[f"commentail_guest_{self.site.pk}"] = remember_guest(
            self.site, "guest@example.invalid"
        )
        comment = accept_request(
            request,
            self.discussion.pk,
            issue_form(request, self.discussion),
            text=LINKS,
            guest_name="Guest",
            guest_email="guest@example.invalid",
            honeypot="autofilled",
        )
        self.assertEqual(
            set(comment.spam_signals), {"many_links", "fast_form", "honeypot"}
        )
        self.assertEqual(comment.status, Comment.Status.PENDING)


class ContentCleanupTests(TransactionTestCase):
    @override_settings(
        COMMENTAIL={"cleanup-content.invalid": {"GUEST_DUPLICATE_WINDOW_SECONDS": 7200}}
    )
    def test_cleanup_respects_site_duplicate_window(self):
        from commentail.background import process_pending

        Locale.objects.get_or_create(language_code="en")
        root = Page.get_first_root_node() or Page.add_root(title="Root", slug="root")
        site = Site.objects.create(hostname="cleanup-content.invalid", root_page=root)
        discussion = Discussion.objects.create(site=site, page=root)
        values = {
            "text": LONG_TEXT,
            "guest_name": "Guest",
            "guest_email": "guest@example.invalid",
        }
        submit(discussion.pk, **values)
        RateEvent.objects.filter(kind="content").update(
            created_at=timezone.now() - timedelta(minutes=90)
        )
        process_pending(mail_limit=1)
        self.assertIn("duplicate_text", submit(discussion.pk, **values).spam_signals)
