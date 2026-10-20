from datetime import timedelta
from html import escape
from urllib.parse import urlencode

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from wagtail.models import Site

from commentail.models import Discussion, MailJob, SiteGroupPermission
from commentail.services import submit


class MailAdminTests(TestCase):
    def setUp(self):
        self.site = Site.objects.get(is_default_site=True)
        self.other = Site.objects.create(
            hostname="foreign.invalid", root_page=self.site.root_page
        )
        self.user = get_user_model().objects.create_user(
            "mail-reviewer", email="synthetic@example.invalid", is_staff=True
        )
        self.group = Group.objects.create(name="Mail reviewers")
        self.group.permissions.add(Permission.objects.get(codename="access_admin"))
        self.user.groups.add(self.group)
        self.grant = SiteGroupPermission.objects.create(
            group=self.group, site=self.site, view=True, moderate=True
        )
        self.comment = submit(
            Discussion.objects.create(site=self.site, page=self.site.root_page).pk,
            text="Synthetic",
            user=self.user,
        )
        foreign = submit(
            Discussion.objects.create(site=self.other, page=self.site.root_page).pk,
            text="Foreign",
            user=self.user,
        )
        self.job = MailJob.objects.create(
            event_key="synthetic-failed",
            kind="published",
            comment=self.comment,
            recipient=self.comment,
            status="failed",
            error="Synthetic error",
            expires_at=timezone.now() + timedelta(days=1),
        )
        self.foreign = MailJob.objects.create(
            event_key="foreign-failed",
            kind="published",
            comment=foreign,
            recipient=foreign,
            status="failed",
            error="FOREIGN ERROR",
            expires_at=timezone.now() + timedelta(days=1),
        )
        self.client.force_login(self.user)
        self.url = reverse("commentail_admin:mail")

    def test_queue_is_site_scoped_and_filter_cannot_expand_access(self):
        response = self.client.get(self.url)
        self.assertContains(response, "Synthetic error")
        self.assertNotContains(response, "FOREIGN ERROR")
        response = self.client.get(self.url, {"site": self.other.pk})
        self.assertNotContains(response, "FOREIGN ERROR")
        self.assertEqual(len(response.context["jobs"]), 0)

    def test_filters_pagination_and_readonly_viewer(self):
        MailJob.objects.bulk_create(
            [
                MailJob(
                    event_key=f"batch-{i}",
                    kind="published",
                    comment=self.comment,
                    recipient=self.comment,
                    status="failed",
                    expires_at=timezone.now() + timedelta(days=1),
                )
                for i in range(32)
            ]
        )
        response = self.client.get(self.url, {"status": "failed", "site": self.site.pk})
        self.assertEqual(len(response.context["jobs"]), 25)
        self.assertIn("status=failed", response.context["next_query"])
        self.assertIn("site=", response.context["next_query"])
        self.assertEqual(
            self.client.get(self.url, {"status": "sent"})
            .context["jobs"]
            .paginator.count,
            0,
        )
        self.grant.moderate = False
        self.grant.save()
        self.assertNotContains(self.client.get(self.url), "Retry delivery")
        self.assertEqual(
            self.client.post(
                reverse("commentail_admin:retry", args=[self.job.pk])
            ).status_code,
            400,
        )
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, "failed")

    def test_queue_retry_returns_to_queue_and_never_uses_untrusted_redirect(self):
        response = self.client.post(
            reverse("commentail_admin:retry", args=[self.job.pk]), {"return_to": "mail"}
        )
        self.assertRedirects(response, self.url)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, "pending")
        self.assertEqual(
            self.client.post(
                reverse("commentail_admin:retry", args=[self.foreign.pk]),
                {"return_to": "mail"},
            ).status_code,
            404,
        )

    def test_card_retry_keeps_comment_selection(self):
        query = "status=&q=Synthetic&p=2"
        card_url = reverse("commentail_admin:detail", args=[self.comment.pk])
        response = self.client.get(card_url, {"return_query": query})
        self.assertContains(response, f'name="return_query" value="{escape(query)}"', count=2)
        response = self.client.post(reverse("commentail_admin:retry", args=[self.job.pk]), {
            "return_query": query,
        })
        self.assertRedirects(response, card_url + "?" + urlencode({"return_query": query}))

    def test_detail_hides_foreign_mail_and_expired_retry(self):
        self.foreign.recipient = self.comment
        self.foreign.save(update_fields=["recipient"])
        self.job.expires_at = timezone.now() - timedelta(seconds=1)
        self.job.save(update_fields=["expires_at"])
        url = reverse("commentail_admin:detail", args=[self.comment.pk])
        response = self.client.get(url)
        self.assertContains(response, "Synthetic error")
        self.assertNotContains(response, "FOREIGN ERROR")
        self.assertNotContains(response, "Retry delivery")
        self.job.expires_at = timezone.now() + timedelta(days=1)
        self.job.save(update_fields=["expires_at"])
        self.assertContains(self.client.get(url), "Retry delivery")
