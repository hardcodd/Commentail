from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import Client, TestCase
from django.urls import reverse
from wagtail.models import Page, Site

from commentail.models import Comment, Discussion, SiteGroupPermission
from commentail.services import moderate, revise, submit


class AdminInterfaceTests(TestCase):
    def setUp(self):
        self.site = Site.objects.get(is_default_site=True)
        self.discussion = Discussion.objects.create(
            site=self.site, page=self.site.root_page
        )
        self.other = Site.objects.create(
            hostname="other.invalid", root_page=self.site.root_page
        )
        self.second = Discussion.objects.create(
            site=self.other, page=self.site.root_page
        )
        self.admin = get_user_model().objects.create_superuser(
            "admin", "admin@example.invalid", "synthetic"
        )
        self.staff = get_user_model().objects.create_user("moderator", is_staff=True)
        group = Group.objects.create(name="Site moderators")
        group.permissions.add(Permission.objects.get(codename="access_admin"))
        self.staff.groups.add(group)
        self.permission = SiteGroupPermission.objects.create(
            group=group, site=self.site, view=True, moderate=True
        )
        self.comment = submit(
            self.discussion.pk, text="Visible queue text", user=self.admin
        )
        self.foreign = submit(
            self.second.pk, text="FOREIGN PRIVATE CONTENT", user=self.admin
        )
        self.client.force_login(self.staff)

    def test_list_and_search_never_disclose_other_site(self):
        response = self.client.get(reverse("commentail_admin:list"))
        self.assertContains(response, "Visible queue text")
        self.assertNotContains(response, "FOREIGN PRIVATE CONTENT")
        self.assertNotContains(response, "other.invalid")
        response = self.client.get(
            reverse("commentail_admin:list"), {"site": self.other.pk, "q": "FOREIGN"}
        )
        self.assertNotContains(response, "FOREIGN PRIVATE CONTENT")

    def test_direct_mutation_cannot_cross_site(self):
        response = self.client.post(
            reverse("commentail_admin:action", args=[self.foreign.pk]),
            {"action": "approve"},
        )
        self.assertEqual(response.status_code, 404)
        self.foreign.refresh_from_db()
        self.assertEqual(self.foreign.status, "pending")

    def test_queue_tabs_count_only_permitted_site_and_keep_filters(self):
        response = self.client.get(reverse("commentail_admin:list"), {"q": "Visible"})
        tabs = response.context["status_tabs"]
        self.assertEqual(tabs[0]["count"], 1)
        self.assertIn("q=Visible", tabs[0]["query"])
        self.assertTrue(tabs[0]["active"])

    def test_page_filter_uses_chooser_without_loading_all_discussion_pages(self):
        page = self.site.root_page.add_child(instance=Page(title="Unselected page", slug="unselected"))
        discussion = Discussion.objects.create(site=self.site, page=page)
        submit(discussion.pk, text="Other page comment", user=self.admin)
        response = self.client.get(reverse("commentail_admin:list"))
        self.assertContains(response, "page-chooser-modal.js")
        self.assertNotContains(response, '<select name="page">')
        self.assertNotContains(response, '<option value="' + str(page.pk) + '"')
        response = self.client.get(reverse("commentail_admin:list"), {"page": page.pk})
        self.assertContains(response, 'name="page" value="' + str(page.pk) + '"')
        self.assertContains(response, "Other page comment")
        self.assertNotContains(response, "Visible queue text")

    def test_page_filter_does_not_resolve_an_unpermitted_page_title(self):
        page = self.site.root_page.add_child(instance=Page(title="Unpermitted target title", slug="foreign-page"))
        Discussion.objects.create(site=self.other, page=page)
        response = self.client.get(reverse("commentail_admin:list"), {"page": page.pk})
        self.assertNotContains(response, "Unpermitted target title")

    def test_tab_counts_include_pending_revisions_without_counting_comment_twice(self):
        moderate(self.comment.pk, "approve", actor=self.admin)
        revise(self.comment.pk, "Pending edit", user=self.admin)
        response = self.client.get(reverse("commentail_admin:list"))
        self.assertEqual([tab["count"] for tab in response.context["status_tabs"]], [1, 1, 0, 1])
        self.assertEqual(response.context["comments"].paginator.count, 1)

    def test_selection_requires_moderation_right_on_each_site(self):
        self.permission.moderate = False
        self.permission.save()
        response = self.client.get(reverse("commentail_admin:list"))
        self.assertNotContains(response, 'name="ids"')

    def test_all_statuses_exposes_actions_for_each_state(self):
        self.client.force_login(self.admin)
        for status in Comment.Status.values:
            with self.subTest(status=status):
                Comment.objects.filter(pk=self.comment.pk).update(status=status)
                response = self.client.get(reverse("commentail_admin:list"), {"status": ""})
                row = next(c for c in response.context["comments"] if c.pk == self.comment.pk)
                expected = {
                    "pending": "approve reject delete",
                    "published": "hide delete",
                    "hidden": "restore delete",
                    "rejected": "delete",
                    "awaiting_email": "delete",
                    "deleted": "",
                }[status]
                self.assertEqual(row.bulk_actions, expected)
                checkbox = f'name="ids" value="{self.comment.pk}"'
                if expected:
                    self.assertContains(response, checkbox + f' data-actions="{expected}"')
                else:
                    self.assertNotContains(response, checkbox)

    def test_bulk_buttons_respect_independent_capabilities(self):
        for capability, status, expected in [
            ("moderate", "pending", "approve reject"),
            ("hide", "published", "hide"),
            ("hide", "hidden", "restore"),
            ("delete", "rejected", "delete"),
        ]:
            with self.subTest(capability=capability, status=status):
                for field in ("moderate", "hide", "delete"):
                    setattr(self.permission, field, field == capability)
                self.permission.save()
                Comment.objects.filter(pk=self.comment.pk).update(status=status)
                response = self.client.get(reverse("commentail_admin:list"), {"status": ""})
                row = next(iter(response.context["comments"]))
                self.assertEqual(row.bulk_actions, expected)
                self.assertEqual([a["value"] for a in response.context["bulk_actions"]], expected.split())

    def test_bulk_hide_restore_and_delete_keep_replies(self):
        self.client.force_login(self.admin)
        moderate(self.comment.pk, "approve", actor=self.admin)
        reply = submit(self.discussion.pk, text="Reply", user=self.admin, reply_to=self.comment.pk)
        for action, status in [("hide", "hidden"), ("restore", "published"), ("delete", "deleted")]:
            with self.subTest(action=action):
                response = self.client.post(reverse("commentail_admin:bulk"), {
                    "action": action, "ids": [self.comment.pk], "return_query": "status=&q=Visible",
                })
                self.assertRedirects(response, reverse("commentail_admin:list") + "?status=&q=Visible")
                self.comment.refresh_from_db()
                self.assertEqual(self.comment.status, status)
                self.assertTrue(Comment.objects.filter(pk=reply.pk).exists())
        self.assertEqual(self.comment.text, "")

    def test_bulk_delete_mixed_statuses_and_duplicate_ids(self):
        self.client.force_login(self.admin)
        moderate(self.foreign.pk, "approve", actor=self.admin)
        response = self.client.post(reverse("commentail_admin:bulk"), {
            "action": "delete", "ids": [self.comment.pk, self.foreign.pk, self.comment.pk],
        }, follow=True)
        self.assertContains(response, "Deleted: 2")
        self.assertEqual(Comment.objects.filter(status="deleted", text="").count(), 2)

    def test_bulk_invalid_status_rolls_back_every_comment(self):
        self.client.force_login(self.admin)
        moderate(self.comment.pk, "approve", actor=self.admin)
        event_count = self.comment.events.count()
        response = self.client.post(reverse("commentail_admin:bulk"), {
            "action": "hide", "ids": [self.comment.pk, self.foreign.pk],
        })
        self.assertEqual(response.status_code, 400)
        self.comment.refresh_from_db()
        self.assertEqual(self.comment.status, "published")
        self.assertEqual(self.comment.events.count(), event_count)

    def test_new_bulk_actions_require_their_own_permission(self):
        for action, status in [("hide", "published"), ("restore", "hidden"), ("delete", "pending")]:
            with self.subTest(action=action):
                Comment.objects.filter(pk=self.comment.pk).update(status=status)
                response = self.client.post(reverse("commentail_admin:bulk"), {
                    "action": action, "ids": [self.comment.pk],
                })
                self.assertEqual(response.status_code, 403)
                self.comment.refresh_from_db()
                self.assertEqual(self.comment.status, status)

    def test_bulk_delete_rolls_back_for_visible_site_without_delete_permission(self):
        self.permission.delete = True
        self.permission.save()
        SiteGroupPermission.objects.create(group=self.permission.group, site=self.other, view=True)
        response = self.client.post(reverse("commentail_admin:bulk"), {
            "action": "delete", "ids": [self.comment.pk, self.foreign.pk],
        })
        self.assertEqual(response.status_code, 403)
        self.comment.refresh_from_db()
        self.assertEqual(self.comment.text, "Visible queue text")

    def test_bulk_deleted_or_unconfirmed_cannot_be_restored_or_approved(self):
        self.client.force_login(self.admin)
        for status in ("deleted", "awaiting_email"):
            for action in ("approve", "reject", "hide", "restore"):
                with self.subTest(status=status, action=action):
                    Comment.objects.filter(pk=self.comment.pk).update(status=status)
                    response = self.client.post(reverse("commentail_admin:bulk"), {
                        "action": action, "ids": [self.comment.pk],
                    })
                    self.assertEqual(response.status_code, 400)

    def test_bulk_validates_request_boundary_without_mutation(self):
        for data in [
            {"action": "delete"},
            {"action": "unknown", "ids": [self.comment.pk]},
            {"action": "delete", "ids": ["bad"]},
            {"action": "delete", "ids": [self.comment.pk] * 101},
        ]:
            with self.subTest(data=data):
                self.assertEqual(self.client.post(reverse("commentail_admin:bulk"), data).status_code, 400)
        self.assertEqual(self.client.get(reverse("commentail_admin:bulk")).status_code, 405)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.admin)
        response = csrf_client.post(reverse("commentail_admin:bulk"), {
            "action": "delete", "ids": [self.comment.pk],
        })
        self.assertEqual(response.status_code, 403)
        self.comment.refresh_from_db()
        self.assertEqual(self.comment.text, "Visible queue text")

    def test_settings_uses_accessible_wagtail_field_errors(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("commentail_admin:settings", args=[self.site.pk]), {}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="id_mode"')
        self.assertContains(response, 'for="id_mode"')
        self.assertContains(response, "This field is required.")

    def test_approve_and_no_text_mutation(self):
        response = self.client.post(
            reverse("commentail_admin:action", args=[self.comment.pk]),
            {"action": "approve", "text": "ATTACK"},
        )
        self.assertEqual(response.status_code, 302)
        self.comment.refresh_from_db()
        self.assertEqual(self.comment.status, "published")
        self.assertEqual(self.comment.text, "Visible queue text")

    def test_hide_requires_separate_right(self):
        moderate(self.comment.pk, "approve", actor=self.admin)
        response = self.client.post(
            reverse("commentail_admin:action", args=[self.comment.pk]),
            {"action": "hide"},
        )
        self.assertEqual(response.status_code, 403)

    def test_moderation_redirect_exposes_a_focusable_result_only_once(self):
        response = self.client.post(
            reverse("commentail_admin:action", args=[self.comment.pk]),
            {"action": "approve"}, follow=True,
        )
        self.assertContains(response, "commentail-action-result")
        self.assertContains(response, f"Comment #{self.comment.pk}: Published")
        self.assertContains(response, "/static/commentail/admin.js")
        response = self.client.get(reverse("commentail_admin:detail", args=[self.comment.pk]))
        self.assertNotContains(response, "commentail-action-result")

    def test_bulk_and_revision_moderation_expose_results(self):
        response = self.client.post(
            reverse("commentail_admin:bulk"),
            {"action": "approve", "ids": [self.comment.pk]}, follow=True,
        )
        self.assertContains(response, "commentail-action-result")
        self.assertContains(response, "Approved: 1")
        revision = revise(self.comment.pk, "Revised text", user=self.admin)
        response = self.client.post(
            reverse("commentail_admin:revision", args=[self.comment.pk]),
            {"action": "reject", "revision": revision.pk}, follow=True,
        )
        self.assertContains(response, "commentail-action-result")
        self.assertContains(response, "Author revision: Rejected")

    def test_bulk_is_atomic_when_foreign_identifier_is_supplied(self):
        response = self.client.post(
            reverse("commentail_admin:bulk"),
            {"action": "approve", "ids": [self.comment.pk, self.foreign.pk]},
        )
        self.assertEqual(response.status_code, 404)
        self.comment.refresh_from_db()
        self.assertEqual(self.comment.status, "pending")

    def test_detail_compares_author_revision_without_editor(self):
        moderate(self.comment.pk, "approve", actor=self.admin)
        revise(self.comment.pk, "Changed author text", user=self.admin)
        response = self.client.get(
            reverse("commentail_admin:detail", args=[self.comment.pk])
        )
        self.assertContains(response, "Changed")
        self.assertContains(response, "Visible")
        self.assertNotContains(response, 'name="text"')

    def test_default_queue_includes_pending_author_revisions(self):
        moderate(self.comment.pk, "approve", actor=self.admin)
        revise(self.comment.pk, "Changed author text", user=self.admin)
        response = self.client.get(reverse("commentail_admin:list"))
        self.assertContains(response, "Visible queue text")
        self.assertContains(response, "Author revision")

    def test_settings_cannot_be_modified_with_moderation_only(self):
        response = self.client.post(
            reverse("commentail_admin:settings", args=[self.site.pk]),
            {"mode": "hidden"},
        )
        self.assertEqual(response.status_code, 403)

    def test_get_action_has_no_effect(self):
        response = self.client.get(
            reverse("commentail_admin:action", args=[self.comment.pk])
        )
        self.assertEqual(response.status_code, 405)

    def test_page_editor_has_connected_settings_and_does_not_leak_cached_panel(self):
        self.client.force_login(self.admin)
        url = reverse("wagtailadmin_pages:edit", args=[self.site.root_page.pk])
        response = self.client.get(url)
        self.assertContains(response, 'name="commentail-mode"')
        from unittest.mock import patch

        with patch("commentail.detection.has_comments", return_value=False):
            response = self.client.get(url)
            self.assertNotContains(response, 'name="commentail-mode"')

    def test_page_settings_saved_with_standard_page_draft(self):
        self.client.force_login(self.admin)
        url = reverse("wagtailadmin_pages:edit", args=[self.site.root_page.pk])
        response = self.client.post(
            url,
            {
                "title": "Changed page title",
                "slug": self.site.root_page.slug,
                "action-save-draft": "1",
                "commentail-enabled": "1",
                "commentail-mode": "read_only",
                "commentail-moderation": "",
                "commentail-access": "",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.discussion.refresh_from_db()
        self.assertEqual(self.discussion.mode, "read_only")

    def test_invalid_settings_do_not_save_page_draft(self):
        self.client.force_login(self.admin)
        page = self.site.root_page
        previous = page.revisions.count()
        response = self.client.post(
            reverse("wagtailadmin_pages:edit", args=[page.pk]),
            {
                "title": "Should not save",
                "slug": page.slug,
                "action-save-draft": "1",
                "commentail-enabled": "1",
                "commentail-max_length": "0",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(page.revisions.count(), previous)

    def test_invalid_revision_identifier_returns_validation_error(self):
        response = self.client.post(
            reverse("commentail_admin:revision", args=[self.comment.pk]),
            {"revision": "bad", "action": "approve"},
        )
        self.assertEqual(response.status_code, 400)

    def test_new_page_saves_settings_in_one_standard_create_action(self):
        from unittest.mock import patch

        from wagtail.models import Page

        self.client.force_login(self.admin)
        url = reverse(
            "wagtailadmin_pages:add",
            args=["wagtailcore", "page", self.site.root_page.pk],
        )
        with patch.object(Page, "is_creatable", True):
            self.assertContains(self.client.get(url), 'name="commentail-mode"')
            response = self.client.post(
                url,
                {
                    "title": "New discussion page",
                    "slug": "new-discussion-page",
                    "action-save-draft": "1",
                    "commentail-enabled": "1",
                    "commentail-mode": "read_only",
                },
            )
        self.assertEqual(response.status_code, 302)
        created = Page.objects.get(slug="new-discussion-page")
        self.assertEqual(
            Discussion.objects.get(page=created, site=self.site).mode, "read_only"
        )
