from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.test import TransactionTestCase, override_settings
from django.utils import timezone
from wagtail.models import Locale, Page, Site

from commentail.models import Discussion, FormTicket


class PeriodicCleanupTests(TransactionTestCase):
    @override_settings(COMMENTAIL={"cleanup.invalid": {"AUTHOR_MIN_INTERVAL": 7200}})
    def test_cleanup_retains_events_needed_by_longer_site_limits(self):
        from commentail.fingerprints import fingerprint
        from commentail.limits import consume
        from commentail.models import RateEvent
        from commentail.services import DomainError

        Locale.objects.get_or_create(language_code="en")
        root = Page.get_first_root_node() or Page.add_root(title="Root", slug="root")
        site = Site.objects.create(hostname="cleanup.invalid", root_page=root)
        event = RateEvent.objects.create(
            site=site,
            kind="comment_author",
            subject_digest=fingerprint(
                "guest:guest@example.invalid", f"rate.{site.pk}.comment_author"
            ),
        )
        expired = RateEvent.objects.create(
            site=site, kind="comment_author", subject_digest="x" * 64
        )
        RateEvent.objects.filter(pk=event.pk).update(
            created_at=timezone.now() - timedelta(minutes=90)
        )
        RateEvent.objects.filter(pk=expired.pk).update(
            created_at=timezone.now() - timedelta(hours=3)
        )
        call_command("process_commentail", stdout=StringIO())
        self.assertTrue(RateEvent.objects.filter(pk=event.pk).exists())
        self.assertFalse(RateEvent.objects.filter(pk=expired.pk).exists())
        with self.assertRaisesMessage(DomainError, "Author limit exceeded"):
            consume(site, "comment", "guest:guest@example.invalid", "127.0.0.1")

    def test_cleanup_removes_expired_tickets_without_revoking_live_forms(self):
        Locale.objects.get_or_create(language_code="en")
        root = Page.get_first_root_node()
        if root is None:
            root = Page.add_root(title="Synthetic root", slug="root")
        site = Site.objects.create(hostname="cleanup.invalid", root_page=root)
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
