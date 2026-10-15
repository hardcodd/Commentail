from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import TestCase
from django.urls import reverse
from wagtail.models import Site

from commentail.models import ModerationRule, SiteGroupPermission


class RuleManagementTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(
            "rules-admin", "", "synthetic"
        )
        self.client.force_login(self.admin)
        self.url = reverse("commentail_admin:rules")
        ModerationRule.objects.bulk_create(
            [
                ModerationRule(
                    phrase=f"Synthetic {i:03}", action="review", enabled=True
                )
                for i in range(61)
            ]
        )

    def test_bounded_stable_pages_and_invalid_page(self):
        first = self.client.get(self.url)
        second = self.client.get(self.url, {"p": 2})
        self.assertEqual(len(first.context["rules"]), 25)
        self.assertEqual(first.context["rules"].paginator.count, 61)
        self.assertTrue(
            {r.pk for r in first.context["rules"]}.isdisjoint(
                r.pk for r in second.context["rules"]
            )
        )
        self.assertEqual(self.client.get(self.url, {"p": "invalid"}).status_code, 200)
        self.assertNotContains(first, 'name="phrase"')

    def test_combined_filters_and_pagination_keep_selection(self):
        ModerationRule.objects.update(action="reject", enabled=False)
        response = self.client.get(
            self.url, {"q": "Synthetic", "action": "reject", "enabled": "0"}
        )
        self.assertEqual(response.context["rules"].paginator.count, 61)
        self.assertIn("q=Synthetic", response.context["next_query"])
        self.assertIn("enabled=0", response.context["next_query"])
        self.assertIn("action=reject", response.context["next_query"])
        self.assertEqual(
            self.client.get(self.url, {"enabled": "1"})
            .context["rules"]
            .paginator.count,
            0,
        )
        self.assertEqual(
            self.client.get(self.url, {"q": "missing"})
            .context["rules"]
            .paginator.count,
            0,
        )

    def test_separate_create_edit_and_validation(self):
        add = reverse("commentail_admin:rule_add")
        response = self.client.post(add, {"phrase": "", "action": "review"})
        self.assertContains(response, "This field is required.")
        self.assertEqual(ModerationRule.objects.count(), 61)
        self.assertRedirects(
            self.client.post(
                add, {"phrase": "New phrase", "action": "reject", "enabled": "on"}
            ),
            self.url,
        )
        rule = ModerationRule.objects.get(phrase="New phrase")
        edit = reverse("commentail_admin:rule_edit", args=[rule.pk])
        self.assertContains(self.client.get(edit), "New phrase")
        self.assertRedirects(
            self.client.post(edit, {"phrase": "Changed phrase", "action": "review"}),
            self.url,
        )
        rule.refresh_from_db()
        self.assertFalse(rule.enabled)
        self.assertEqual(rule.phrase, "Changed phrase")
        self.assertEqual(ModerationRule.objects.count(), 62)
        self.assertRedirects(self.client.get(self.url, {"id": rule.pk}), edit)

    def test_rules_capability_required_for_every_route(self):
        user = get_user_model().objects.create_user("viewer", is_staff=True)
        group = Group.objects.create(name="Rule access")
        group.permissions.add(Permission.objects.get(codename="access_admin"))
        user.groups.add(group)
        grant = SiteGroupPermission.objects.create(
            group=group, site=Site.objects.get(is_default_site=True), view=True
        )
        self.client.force_login(user)
        self.client.defaults["HTTP_X_REQUESTED_WITH"] = "XMLHttpRequest"
        edit = reverse(
            "commentail_admin:rule_edit", args=[ModerationRule.objects.first().pk]
        )
        add = reverse("commentail_admin:rule_add")
        for url in (self.url, edit, add):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 403, str(response.headers))
            self.assertEqual(
                self.client.post(
                    url, {"phrase": "Denied", "action": "review"}
                ).status_code,
                403,
            )
        grant.rules = True
        grant.save()
        self.assertEqual(self.client.get(self.url).status_code, 200)
