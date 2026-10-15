from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from wagtail.models import Site

from commentail.models import Discussion, FormTicket


class PeriodicCleanupTests(TestCase):
    def test_cleanup_removes_expired_tickets_without_revoking_live_forms(self):
        site = Site.objects.get(is_default_site=True)
        discussion = Discussion.objects.create(site=site, page=site.root_page)
        expired = FormTicket.objects.create(
            digest="a" * 64,
            discussion=discussion,
            session_digest="s" * 64,
            expires_at=timezone.now() - timedelta(seconds=1),
        )
        live = FormTicket.objects.create(
            digest="b" * 64,
            discussion=discussion,
            session_digest="s" * 64,
            expires_at=timezone.now() + timedelta(minutes=1),
        )
        call_command("process_commentail", stdout=StringIO())
        self.assertFalse(FormTicket.objects.filter(pk=expired.pk).exists())
        self.assertTrue(FormTicket.objects.filter(pk=live.pk).exists())
