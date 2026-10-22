"""Translated home trees retain Site-scoped access without admitting foreign trees."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.contrib.sessions.middleware import SessionMiddleware
from django.core import mail
from django.template import Context, Template
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from wagtail.models import Locale, Page, PageViewRestriction, Site

from commentail.admission import can_view
from commentail.models import Comment, Discussion, MailJob
from commentail.outbox import process_mail
from commentail.recent import recent_comments
from commentail.security import issue_token
from commentail.services import submit


@override_settings(
    WAGTAIL_I18N_ENABLED=True,
    WAGTAIL_CONTENT_LANGUAGES=[("en", "English"), ("ru", "Russian")],
)
class TranslatedSiteRootTests(TestCase):
    def setUp(self):
        self.site = Site.objects.get(is_default_site=True)
        locale, _ = Locale.objects.get_or_create(language_code="ru")
        self.translated_root = self.site.root_page.copy_for_translation(locale)
        self.translated_root.live = True
        self.translated_root.save()
        original = self.site.root_page.add_child(
            instance=Page(title="Article", slug="article")
        )
        self.page = original.copy_for_translation(locale)
        self.page.live = True
        self.page.save()
        self.discussion = Discussion.objects.create(site=self.site, page=self.page)
        self.request = RequestFactory().get("/")
        self.request.user = AnonymousUser()
        SessionMiddleware(lambda request: None).process_request(self.request)

    def recent(self):
        return recent_comments(self.request, limit=5, page=None, include_replies=True)

    def published(self):
        return Comment.objects.create(
            discussion=self.discussion,
            text="Translated public comment",
            guest_name="Guest",
            status=Comment.Status.PUBLISHED,
            published_at=timezone.now(),
        )

    def test_translated_root_and_descendant_can_open_forms(self):
        for page in (self.site.root_page, self.translated_root, self.page):
            with self.subTest(page=page.pk):
                response = self.client.get(
                    reverse("commentail:discussion", args=[page.pk])
                )
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context["form_key"])

    def test_translated_page_accepts_registered_submission(self):
        author = get_user_model().objects.create_user("translated-author")
        self.client.force_login(author)
        response = self.client.get(
            reverse("commentail:discussion", args=[self.page.pk])
        )
        self.assertEqual(response.status_code, 200)
        response = self.client.post(
            reverse("commentail:submit", args=[self.page.pk]),
            {"key": response.context["form_key"], "text": "Translated submission"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            self.discussion.comments.filter(
                user=author, text="Translated submission"
            ).exists()
        )

    def test_recent_comments_include_translated_tree(self):
        comment = self.published()
        self.assertEqual([row["id"] for row in self.recent()], [comment.pk])

    def test_host_widget_renders_existing_translated_comments(self):
        comment = self.published()
        rendered = Template("{% load commentail_tags %}{% commentail page %}").render(
            Context({"request": self.request, "page": self.page})
        )
        self.assertIn(comment.text, rendered)
        self.assertIn('name="key"', rendered)

    def test_guest_capability_and_mail_remain_available(self):
        comment = submit(
            self.discussion.pk,
            text="Translated pending comment",
            guest_name="Guest",
            guest_email="translated@example.invalid",
        )
        secret = issue_token(comment, "view", timezone.now() + timedelta(hours=1))
        response = self.client.get(
            reverse("commentail:action", args=["view"]), {"token": secret}
        )
        self.assertContains(response, comment.text)
        self.assertEqual(process_mail(), 1)
        self.assertEqual(len(mail.outbox), 1)

    def test_private_translated_tree_cancels_guest_mail(self):
        comment = submit(
            self.discussion.pk,
            text="Private translated comment",
            guest_name="Guest",
            guest_email="translated@example.invalid",
        )
        PageViewRestriction.objects.create(
            page=self.translated_root, restriction_type="login"
        )
        self.assertEqual(process_mail(), 0)
        self.assertEqual(MailJob.objects.get(comment=comment).status, "cancelled")

    def test_disabled_i18n_cancels_translated_guest_mail(self):
        comment = submit(
            self.discussion.pk,
            text="Translated comment with disabled i18n",
            guest_name="Guest",
            guest_email="translated@example.invalid",
        )
        with override_settings(WAGTAIL_I18N_ENABLED=False):
            self.assertEqual(process_mail(), 0)
        self.assertEqual(MailJob.objects.get(comment=comment).status, "cancelled")

    def test_translation_is_not_allowed_when_i18n_is_disabled(self):
        self.published()
        with override_settings(WAGTAIL_I18N_ENABLED=False):
            self.assertFalse(can_view(self.request, self.discussion))
            self.assertEqual(self.recent(), [])
            self.assertEqual(
                self.client.get(
                    reverse("commentail:discussion", args=[self.page.pk])
                ).status_code,
                404,
            )

    def test_translated_tree_still_enforces_inherited_restrictions(self):
        self.published()
        PageViewRestriction.objects.create(
            page=self.translated_root, restriction_type="login"
        )
        self.assertFalse(can_view(self.request, self.discussion))
        self.assertEqual(self.recent(), [])
        self.request.user = get_user_model().objects.create_user("translated-reader")
        self.assertTrue(can_view(self.request, self.discussion))
        self.assertEqual(len(self.recent()), 1)

    def test_translated_leaf_outside_home_tree_is_not_admitted(self):
        original = self.site.root_page.add_child(
            instance=Page(title="Sibling article", slug="sibling-article")
        )
        foreign = Page.get_first_root_node().add_child(
            instance=Page(
                title="Misplaced translation",
                slug="misplaced-translation",
                locale=self.translated_root.locale,
                translation_key=original.translation_key,
            )
        )
        discussion = Discussion.objects.create(site=self.site, page=foreign)
        self.assertFalse(can_view(self.request, discussion))
        self.assertEqual(
            self.client.get(
                reverse("commentail:discussion", args=[foreign.pk])
            ).status_code,
            404,
        )

    def test_unpublished_translation_stays_hidden(self):
        self.published()
        self.page.live = False
        self.page.save(update_fields=["live"])
        self.assertFalse(can_view(self.request, self.discussion))
        self.assertEqual(self.recent(), [])

    def test_moving_page_outside_translated_tree_revokes_all_access(self):
        comment = submit(
            self.discussion.pk,
            text="Moved translated pending comment",
            guest_name="Guest",
            guest_email="translated@example.invalid",
        )
        secret = issue_token(comment, "view", timezone.now() + timedelta(hours=1))
        foreign = Page.get_first_root_node().add_child(
            instance=Page(title="Foreign", slug="translated-foreign")
        )
        self.page.move(foreign, pos="last-child")
        self.page.refresh_from_db()
        self.discussion.page = self.page
        self.assertFalse(can_view(self.request, self.discussion))
        response = self.client.get(
            reverse("commentail:action", args=["view"]), {"token": secret}
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(process_mail(), 0)
        self.assertEqual(MailJob.objects.get(comment=comment).status, "cancelled")
        self.published()
        self.assertEqual(self.recent(), [])

    def test_other_site_cannot_use_translated_capability(self):
        other_root = Page.get_first_root_node().add_child(
            instance=Page(title="Other Site", slug="translation-other-site")
        )
        Site.objects.create(hostname="other.invalid", root_page=other_root)
        comment = self.published()
        secret = issue_token(comment, "view", timezone.now() + timedelta(hours=1))
        response = self.client.get(
            reverse("commentail:action", args=["view"]),
            {"token": secret},
            HTTP_HOST="other.invalid",
        )
        self.assertEqual(response.status_code, 404)
