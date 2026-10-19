from bs4 import BeautifulSoup
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse
from wagtail.models import Site

from commentail.forms import DiscussionSettingsForm, SiteSettingsForm
from commentail.models import Comment, Discussion, SiteCommentSettings
from commentail.services import moderate, submit


class StaffAuthorTests(TestCase):
    def setUp(self):
        self.site = Site.objects.get(is_default_site=True)
        self.discussion = Discussion.objects.create(site=self.site, page=self.site.root_page)
        self.admin = get_user_model().objects.create_superuser(
            "owner", "owner@example.invalid", "synthetic",
        )
        self.staff = get_user_model().objects.create_user("editor", is_staff=True)
        self.reader = get_user_model().objects.create_user("reader")
        self.url = reverse("commentail:discussion", args=[self.site.root_page.pk])

    def publish(self, user, *, reply_to=None):
        comment = submit(self.discussion.pk, text="A comment", user=user, reply_to=reply_to)
        moderate(comment.pk, "approve", actor=self.admin)
        return comment

    def card(self, comment, **query):
        response = self.client.get(self.url, query)
        self.assertEqual(response.status_code, 200)
        return BeautifulSoup(response.content, "html.parser").select_one(f"#commentail-{comment.pk}")

    def test_default_highlights_staff_and_crowns_only_superusers(self):
        for user, highlighted, crowned in [
            (self.reader, False, False), (self.staff, True, False), (self.admin, True, True),
        ]:
            with self.subTest(user=user.username):
                card = self.card(self.publish(user))
                self.assertEqual(bool(card.select_one("strong.commentail-staff-name")), highlighted)
                self.assertEqual(bool(card.select_one(".commentail-crown")), crowned)
                self.assertEqual(bool(card.select_one("strong.commentail-superuser-name")), crowned)
                self.assertEqual(card.select_one("strong").get_text(strip=True), user.username)
                self.assertEqual(card.select_one('[itemprop="name"]').text, user.username)

    def test_switch_is_site_only_enabled_by_default_and_removes_both_marks(self):
        self.assertTrue(SiteCommentSettings().highlight_staff)
        self.assertIn("highlight_staff", SiteSettingsForm().fields)
        self.assertNotIn("highlight_staff", DiscussionSettingsForm().fields)
        settings = SiteCommentSettings.objects.create(site=self.site, highlight_staff=False)
        comment = self.publish(self.admin)
        card = self.card(comment)
        self.assertFalse(card.select(".commentail-staff-name, .commentail-crown"))
        settings.highlight_staff = True
        settings.save()
        self.assertTrue(self.card(comment).select_one(".commentail-crown"))

    def test_other_site_setting_does_not_disable_this_site(self):
        other = Site.objects.create(hostname="other.invalid", root_page=self.site.root_page)
        SiteCommentSettings.objects.create(site=other, highlight_staff=False)
        self.assertTrue(self.card(self.publish(self.staff)).select_one(".commentail-staff-name"))

    def test_current_roles_and_account_deletion_change_existing_comments(self):
        comment = self.publish(self.staff)
        self.staff.is_staff = False
        self.staff.save()
        self.assertFalse(self.card(comment).select_one(".commentail-staff-name"))
        self.staff.is_staff = True
        self.staff.is_active = False
        self.staff.save()
        self.assertFalse(self.card(comment).select_one(".commentail-staff-name"))
        self.staff.delete()
        self.assertFalse(self.card(comment).select_one(".commentail-staff-name"))

    def test_guest_cannot_impersonate_highlighted_name(self):
        guest = submit(self.discussion.pk, text="Guest", guest_name="owner",
                       guest_email="guest@example.invalid")
        Comment.objects.filter(pk=guest.pk).update(status="pending")
        moderate(guest.pk, "approve", actor=self.admin)
        self.assertFalse(self.card(guest).select(".commentail-staff-name, .commentail-crown"))

    def test_replies_and_own_pending_cards_use_the_same_author_rendering(self):
        parent = self.publish(self.reader)
        reply = self.publish(self.staff, reply_to=parent.pk)
        self.assertTrue(self.card(reply, thread=parent.pk).select_one(".commentail-staff-name"))
        self.client.force_login(self.admin)
        pending = submit(self.discussion.pk, text="Private pending", user=self.admin)
        response = self.client.get(self.url)
        markup = BeautifulSoup(response.content, "html.parser")
        self.assertTrue(markup.select_one(
            f"#commentail-private-{pending.pk} .commentail-avatar-wrap .commentail-crown"
        ))
        SiteCommentSettings.objects.create(site=self.site, highlight_staff=False)
        self.assertNotContains(self.client.get(self.url), 'class="commentail-crown"')

    def test_staff_name_remains_escaped_and_crown_has_an_accessible_label(self):
        self.admin.first_name = '<script>alert("name")</script>'
        self.admin.save()
        card = self.card(self.publish(self.admin))
        self.assertFalse(card.select("script"))
        self.assertIn("<script>", card.select_one("strong").get_text())
        crown = card.select_one(".commentail-crown")
        self.assertEqual(crown["role"], "img")
        self.assertEqual(crown["aria-label"], "Super administrator")
        self.assertIsNone(crown.find_parent(attrs={"aria-hidden": "true"}))
        self.assertIsNotNone(card.select_one(".commentail-avatar-wrap .commentail-crown"))
        self.assertIsNone(card.select_one("strong .commentail-crown"))

    def test_site_setting_can_be_saved_only_by_authorized_user(self):
        url = reverse("commentail_admin:settings", args=[self.site.pk])
        self.client.force_login(self.admin)
        response = self.client.post(url, {
            "mode": "open", "moderation": "all", "access": "all", "max_length": 5000,
        })
        self.assertEqual(response.status_code, 302)
        self.assertFalse(SiteCommentSettings.objects.get(site=self.site).highlight_staff)
        self.client.force_login(self.staff)
        self.staff.user_permissions.add(Permission.objects.get(codename="access_admin"))
        self.assertEqual(self.client.post(url, {"highlight_staff": "on"}).status_code, 403)
        self.assertFalse(SiteCommentSettings.objects.get(site=self.site).highlight_staff)
