from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import TestCase
from django.urls import reverse
from wagtail.models import Site

from commentail.models import SiteGroupPermission


class GroupPanelTests(TestCase):
    def setUp(self):
        self.site = Site.objects.get(is_default_site=True)
        self.group = Group.objects.create(name="Commentail reviewers")
        self.access = Permission.objects.get(codename="access_admin")
        self.group.permissions.add(self.access)
        self.admin = get_user_model().objects.create_superuser(
            "admin", "admin@example.invalid", "synthetic"
        )
        self.client.force_login(self.admin)
        self.url = reverse("wagtailusers_groups:edit", args=[self.group.pk])

    def payload(self, url=None):
        response = self.client.get(url or self.url)
        data = {"name": "Commentail reviewers", "permissions": [self.access.pk]}
        for panel in response.context["permission_panels"]:
            for field in panel.management_form:
                data[field.html_name] = field.value()
        data.update(
            {
                "commentail_permissions-TOTAL_FORMS": "1",
                "commentail_permissions-INITIAL_FORMS": "0",
                "commentail_permissions-0-site": str(self.site.pk),
                "commentail_permissions-0-view": "on",
                "commentail_permissions-0-moderate": "on",
            }
        )
        return data

    def test_panel_displays_existing_grants_without_mutation(self):
        grant = SiteGroupPermission.objects.create(
            group=self.group, site=self.site, view=True
        )
        response = self.client.get(self.url)
        self.assertContains(response, "Comment permissions by site")
        self.assertContains(response, 'name="commentail_permissions-0-site"')
        grant.refresh_from_db()
        self.assertTrue(grant.view)
        self.assertFalse(grant.moderate)

    def test_save_group_updates_same_records_and_preserves_native_permissions(self):
        grant = SiteGroupPermission.objects.create(
            group=self.group, site=self.site, view=True, hide=True
        )
        other = Group.objects.create(name="Other group")
        untouched = SiteGroupPermission.objects.create(
            group=other, site=self.site, delete=True
        )
        response = self.client.post(self.url, self.payload())
        self.assertEqual(response.status_code, 302)
        grant.refresh_from_db()
        untouched.refresh_from_db()
        self.assertTrue(grant.moderate)
        self.assertFalse(grant.hide)
        self.assertTrue(untouched.delete)
        self.assertTrue(self.group.permissions.filter(pk=self.access.pk).exists())

    def test_duplicate_sites_and_invalid_site_do_not_save_group(self):
        data = self.payload()
        data["name"] = "Must not persist"
        data["commentail_permissions-TOTAL_FORMS"] = "2"
        data["commentail_permissions-1-site"] = str(self.site.pk)
        data["commentail_permissions-1-view"] = "on"
        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Each site may appear only once.")
        self.group.refresh_from_db()
        self.assertEqual(self.group.name, "Commentail reviewers")
        data = self.payload()
        data["commentail_permissions-0-site"] = "999999"
        self.assertEqual(self.client.post(self.url, data).status_code, 200)
        self.assertFalse(SiteGroupPermission.objects.filter(group=self.group).exists())

    def test_group_creation_saves_panel(self):
        url = reverse("wagtailusers_groups:add")
        data = self.payload(url)
        data["name"] = "New reviewers"
        self.assertEqual(self.client.post(url, data).status_code, 302)
        self.assertTrue(
            SiteGroupPermission.objects.get(group__name="New reviewers").moderate
        )

    def test_deleted_row_revokes_grant(self):
        SiteGroupPermission.objects.create(group=self.group, site=self.site, view=True)
        data = self.payload()
        data["commentail_permissions-0-DELETE"] = "on"
        self.assertEqual(self.client.post(self.url, data).status_code, 302)
        self.assertFalse(SiteGroupPermission.objects.filter(group=self.group).exists())

    def test_missing_panel_management_does_not_silently_revoke(self):
        SiteGroupPermission.objects.create(group=self.group, site=self.site, view=True)
        data = self.payload()
        del data["commentail_permissions-TOTAL_FORMS"]
        self.assertEqual(self.client.post(self.url, data).status_code, 200)
        self.assertTrue(
            SiteGroupPermission.objects.filter(group=self.group, view=True).exists()
        )

    def test_moderator_without_group_edit_permission_is_denied(self):
        user = get_user_model().objects.create_user("moderator", is_staff=True)
        user.groups.add(self.group)
        SiteGroupPermission.objects.create(
            group=self.group, site=self.site, view=True, moderate=True
        )
        data = self.payload()
        self.client.force_login(user)
        self.assertEqual(self.client.get(self.url).status_code, 302)
        self.assertEqual(self.client.post(self.url, data).status_code, 302)
        self.assertFalse(SiteGroupPermission.objects.get(group=self.group).settings)
