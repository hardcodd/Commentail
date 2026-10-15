from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from wagtail.models import Page, Site

from commentail.models import (
    Comment,
    CommentRevision,
    Discussion,
    ModerationRule,
    SiteCommentSettings,
)
from commentail.services import (
    DomainError,
    cleanup_unconfirmed,
    confirm_email,
    hide,
    moderate,
    moderate_revision,
    remove,
    restore,
    revise,
    submit,
)


class LifecycleTests(TestCase):
    def setUp(self):
        self.site = Site.objects.get(is_default_site=True)
        self.page = self.site.root_page
        self.discussion = Discussion.objects.create(site=self.site, page=self.page)
        self.author = get_user_model().objects.create_user(
            "writer", email="writer@example.invalid"
        )
        self.other = get_user_model().objects.create_user("other")
        self.moderator = get_user_model().objects.create_superuser(
            "moderator", "admin@example.invalid", "synthetic"
        )
        self.options = SiteCommentSettings.objects.create(site=self.site)

    def post(self, text="Original", **kwargs):
        return submit(self.discussion.pk, text=text, user=self.author, **kwargs)

    def publish(self, comment):
        return moderate(comment.pk, "approve", actor=self.moderator)

    def test_default_moderation(self):
        comment = self.post()
        self.assertEqual(comment.status, Comment.Status.PENDING)
        self.assertIsNone(comment.published_at)
        published = self.publish(comment)
        self.assertEqual(published.status, Comment.Status.PUBLISHED)
        self.assertIsNotNone(published.published_at)

    def test_guest_confirmation_before_rules(self):
        self.options.moderation = "rules"
        self.options.save()
        ModerationRule.objects.create(phrase="bad", action="reject")
        comment = submit(
            self.discussion.pk,
            text="BAD",
            guest_name="Guest",
            guest_email="guest@example.invalid",
        )
        self.assertEqual(comment.status, Comment.Status.AWAITING_EMAIL)
        confirmed = confirm_email(comment.pk)
        self.assertEqual(confirmed.status, Comment.Status.REJECTED)
        self.assertIsNotNone(confirmed.email_confirmed_at)

    def test_guest_fields_required(self):
        for fields in [
            {},
            {"guest_name": "Guest"},
            {"guest_email": "a@example.invalid"},
        ]:
            with self.subTest(fields=fields), self.assertRaises(DomainError):
                submit(self.discussion.pk, text="Message", **fields)

    def test_registered_and_guest_policies(self):
        for policy, expected in [
            ("all", "pending"),
            ("guests", "published"),
            ("none", "published"),
            ("rules", "published"),
        ]:
            self.options.moderation = policy
            self.options.save()
            with self.subTest(policy=policy):
                self.assertEqual(self.post().status, expected)

    def test_rule_normalization_and_priority(self):
        self.options.moderation = "rules"
        self.options.save()
        ModerationRule.objects.create(phrase="плохой", action="review")
        ModerationRule.objects.create(phrase="ёлки палки", action="reject")
        comment = self.post("ПЛОХОЙ! ЕЛКИ,\n   ПАЛКИ")
        self.assertEqual(comment.status, "rejected")
        self.assertEqual(self.post("неплохой").status, "published")

    def test_suspicion_does_not_override_rejection(self):
        self.options.moderation = "rules"
        self.options.save()
        ModerationRule.objects.create(phrase="bad", action="reject")
        self.assertEqual(self.post("bad", suspicious=True).status, "rejected")
        self.assertEqual(self.post("good", suspicious=True).status, "pending")

    def test_page_override_and_current_inheritance(self):
        self.discussion.moderation = "none"
        self.discussion.save()
        self.assertEqual(self.post().status, "published")
        self.discussion.moderation = ""
        self.discussion.save()
        self.assertEqual(self.post().status, "pending")

    def test_old_queue_not_reprocessed(self):
        comment = self.post()
        self.options.moderation = "none"
        self.options.save()
        comment.refresh_from_db()
        self.assertEqual(comment.status, "pending")

    def test_reply_locks_immediately_and_permanently(self):
        target = self.publish(self.post())
        reply = self.post("Reply", reply_to=target.pk)
        self.assertEqual(reply.status, "pending")
        with self.assertRaises(DomainError):
            revise(target.pk, "Changed", user=self.author)
        remove(reply.pk, actor=self.moderator)
        with self.assertRaises(DomainError):
            revise(target.pk, "Changed", user=self.author)

    def test_reply_to_reply_has_one_root(self):
        root = self.publish(self.post())
        first = self.publish(self.post(reply_to=root.pk))
        second = self.post(reply_to=first.pk)
        self.assertEqual(second.root_id, root.pk)
        self.assertEqual(second.reply_to_id, first.pk)

    def test_invalid_reply_targets(self):
        pending = self.post()
        with self.assertRaises(DomainError):
            self.post(reply_to=pending.pk)
        other = Discussion.objects.create(
            site=Site.objects.create(hostname="other.invalid", root_page=self.page),
            page=self.page,
        )
        target = self.publish(submit(other.pk, text="Other", user=self.author))
        with self.assertRaises(DomainError):
            self.post(reply_to=target.pk)

    def test_pending_revision_preserves_text_and_blocks_new(self):
        comment = self.publish(self.post())
        revision = revise(comment.pk, "New", user=self.author)
        self.assertEqual(revision.status, "pending")
        comment.refresh_from_db()
        self.assertEqual(comment.text, "Original")
        with self.assertRaises(DomainError):
            revise(comment.pk, "Again", user=self.author)
        self.post(reply_to=comment.pk)
        moderate_revision(revision.pk, "approve", actor=self.moderator)
        comment.refresh_from_db()
        revision.refresh_from_db()
        self.assertEqual(comment.text, "New")
        self.assertEqual(revision.text, "")
        self.assertIsNotNone(comment.edited_at)

    def test_rejected_revision_keeps_public_version(self):
        comment = self.publish(self.post())
        revision = revise(comment.pk, "New", user=self.author)
        moderate_revision(revision.pk, "reject", actor=self.moderator, reason="Reason")
        comment.refresh_from_db()
        revision.refresh_from_db()
        self.assertEqual(comment.text, "Original")
        self.assertEqual(revision.text, "")
        self.assertEqual(revision.reason, "Reason")

    def test_revision_rules_and_immediate_publication(self):
        comment = self.publish(self.post())
        self.options.moderation = "rules"
        self.options.save()
        ModerationRule.objects.create(phrase="bad", action="reject")
        rejected = revise(comment.pk, "bad", user=self.author)
        comment.refresh_from_db()
        self.assertEqual(rejected.status, "rejected")
        self.assertEqual(comment.text, "Original")
        self.assertEqual(rejected.text, "")
        accepted = revise(comment.pk, "Good", user=self.author)
        comment.refresh_from_db()
        self.assertEqual(accepted.status, "approved")
        self.assertEqual(comment.text, "Good")

    def test_exact_edit_window_and_owner(self):
        comment = self.publish(self.post())
        with self.assertRaises(DomainError):
            revise(comment.pk, "New", user=self.other)
        Comment.objects.filter(pk=comment.pk).update(
            published_at=timezone.now() - timedelta(minutes=15)
        )
        with self.assertRaises(DomainError):
            revise(comment.pk, "New", user=self.author)

    def test_closed_discussion_blocks_authors_not_moderation(self):
        comment = self.post()
        self.discussion.mode = "read_only"
        self.discussion.save()
        with self.assertRaises(DomainError):
            self.post()
        comment = self.publish(comment)
        with self.assertRaises(DomainError):
            revise(comment.pk, "New", user=self.author)

    def test_moderator_cannot_change_text_or_delete_as_author(self):
        comment = self.publish(self.post())
        with self.assertRaises(DomainError):
            revise(comment.pk, "Moderator text", user=self.moderator)
        with self.assertRaises(DomainError):
            remove(comment.pk, actor=self.author)

    def test_deletion_erases_versions_and_preserves_replies(self):
        comment = self.publish(self.post())
        revision = revise(comment.pk, "Secret revision", user=self.author)
        reply = self.post(reply_to=comment.pk)
        remove(comment.pk, actor=self.moderator)
        comment.refresh_from_db()
        self.assertEqual(comment.text, "")
        self.assertEqual(comment.status, "deleted")
        self.assertTrue(Comment.objects.filter(pk=reply.pk).exists())
        self.assertFalse(CommentRevision.objects.filter(pk=revision.pk).exists())
        with self.assertRaises(DomainError):
            restore(comment.pk, actor=self.moderator)

    def test_hide_restore_preserves_publication_time(self):
        comment = self.publish(self.post())
        original = comment.published_at
        hide(comment.pk, actor=self.moderator)
        restored = restore(comment.pk, actor=self.moderator)
        self.assertEqual(restored.published_at, original)
        self.assertEqual(restored.text, "Original")

    def test_expiry_and_repeat_confirmation(self):
        comment = submit(
            self.discussion.pk,
            text="Guest",
            guest_name="Guest",
            guest_email="a@example.invalid",
        )
        confirmed = confirm_email(comment.pk)
        self.assertEqual(confirm_email(comment.pk).status, confirmed.status)
        expired = submit(
            self.discussion.pk,
            text="Expire",
            guest_name="Guest",
            guest_email="a@example.invalid",
        )
        Comment.objects.filter(pk=expired.pk).update(
            created_at=timezone.now() - timedelta(hours=24)
        )
        with self.assertRaises(DomainError):
            confirm_email(expired.pk)
        self.assertEqual(cleanup_unconfirmed(), 1)
        self.assertFalse(Comment.objects.filter(pk=expired.pk).exists())

    def test_account_deletion_anonymizes(self):
        comment = self.post()
        self.author.delete()
        comment.refresh_from_db()
        self.assertIsNone(comment.user_id)
        self.assertEqual(comment.email, "")
        self.assertTrue(comment.account_deleted)
        self.assertEqual(comment.display_name, "Deleted user")

    def test_page_deletion_cascades(self):
        root = Page.get_first_root_node()
        page = root.add_child(instance=Page(title="Synthetic", slug="synthetic"))
        discussion = Discussion.objects.create(site=self.site, page=page)
        comment = submit(discussion.pk, text="Original", user=self.author)
        page.delete()
        self.assertFalse(Comment.objects.filter(pk=comment.pk).exists())

    def test_invalid_text(self):
        for text in ["", "   ", "a" * 5001]:
            with self.subTest(text=text[:10]), self.assertRaises(DomainError):
                self.post(text)

    def test_group_actions_and_site_are_independent(self):
        from django.contrib.auth.models import Group

        from commentail.models import SiteGroupPermission

        group = Group.objects.create(name="Reviewers")
        self.other.groups.add(group)
        SiteGroupPermission.objects.create(group=group, site=self.site, moderate=True)
        comment = self.post()
        moderate(comment.pk, "approve", actor=self.other)
        with self.assertRaises(DomainError):
            hide(comment.pk, actor=self.other)
        with self.assertRaises(DomainError):
            remove(comment.pk, actor=self.other)
        second = Site.objects.create(hostname="different.invalid", root_page=self.page)
        discussion = Discussion.objects.create(site=second, page=self.page)
        foreign = submit(discussion.pk, text="Private", user=self.author)
        with self.assertRaises(DomainError):
            moderate(foreign.pk, "approve", actor=self.other)

    def test_repeat_moderation_has_one_event(self):
        comment = self.post()
        self.publish(comment)
        self.publish(comment)
        self.assertEqual(comment.events.count(), 1)

    def test_author_access_categories(self):
        self.options.access = "guests"
        self.options.save()
        with self.assertRaises(DomainError):
            self.post()
        self.options.access = "registered"
        self.options.save()
        with self.assertRaises(DomainError):
            submit(
                self.discussion.pk,
                text="Guest",
                guest_name="G",
                guest_email="g@example.invalid",
            )

    def test_account_name_is_current_and_email_is_not_public(self):
        comment = self.post()
        self.author.first_name = "Current"
        self.author.save()
        comment.refresh_from_db()
        self.assertEqual(comment.display_name, "Current")
        self.author.first_name = ""
        self.author.username = "private@example.invalid"
        self.author.save()
        comment.refresh_from_db()
        self.assertEqual(comment.display_name, "User")

    def test_failed_submission_does_not_lock_recipient(self):
        comment = self.publish(self.post())
        with self.assertRaises(DomainError):
            self.post("", reply_to=comment.pk)
        comment.refresh_from_db()
        self.assertFalse(comment.edit_locked)

    def test_length_counts_graphemes(self):
        self.options.max_length = 1
        self.options.save()
        for text in ["👨‍👩‍👧‍👦", "👍🏽", "🇬🇧", "é"]:
            with self.subTest(text=text):
                self.assertEqual(self.post(text).text, text)
        with self.assertRaises(DomainError):
            self.post("👍🏽x")

    def test_default_links_are_disabled(self):
        from commentail.policies import editorial_settings

        self.assertFalse(editorial_settings(self.discussion).clickable_links)

    def test_guest_name_limit_after_trimming(self):
        comment = submit(
            self.discussion.pk,
            text="Guest",
            guest_name=" " + "a" * 80 + " ",
            guest_email="guest@example.invalid",
        )
        self.assertEqual(comment.guest_name, "a" * 80)
