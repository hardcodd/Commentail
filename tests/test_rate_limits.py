from datetime import timedelta

from django.test import RequestFactory, TestCase, override_settings
from django.utils import timezone
from wagtail.models import Site

from commentail.limits import client_ip, consume
from commentail.models import RateEvent
from commentail.services import DomainError


class LimitTests(TestCase):
    def setUp(self):
        self.site = Site.objects.get(is_default_site=True)

    def test_author_interval_and_atomic_ip_rejection(self):
        consume(self.site, "comment", "user:1", "127.0.0.1")
        with self.assertRaises(DomainError):
            consume(self.site, "comment", "user:1", "127.0.0.2")
        self.assertEqual(RateEvent.objects.count(), 2)

    def test_rolling_window_and_site_scope(self):
        with override_settings(COMMENTAIL={"default": {"AUTHOR_LIMIT_PER_HOUR": 1}}):
            consume(self.site, "comment", "user:1", "127.0.0.1")
            second = Site.objects.create(
                hostname="second.invalid", root_page=self.site.root_page
            )
            consume(second, "comment", "user:1", "127.0.0.1")
            RateEvent.objects.filter(site=self.site).update(
                created_at=timezone.now() - timedelta(seconds=31)
            )
            with self.assertRaises(DomainError):
                consume(self.site, "comment", "user:1", "127.0.0.1")
            RateEvent.objects.filter(site=self.site).update(
                created_at=timezone.now() - timedelta(hours=1)
            )
            consume(self.site, "comment", "user:1", "127.0.0.1")

    def test_ip_limit_is_independent(self):
        with override_settings(COMMENTAIL={"default": {"IP_LIMIT_PER_HOUR": 1}}):
            consume(self.site, "comment", "user:1", "127.0.0.1")
            with self.assertRaises(DomainError):
                consume(self.site, "comment", "user:2", "127.0.0.1")
            self.assertEqual(RateEvent.objects.count(), 2)

    def test_captcha_refresh_shares_counter(self):
        for _ in range(10):
            consume(self.site, "captcha", "", "127.0.0.1")
        with self.assertRaises(DomainError):
            consume(self.site, "captcha", "", "127.0.0.1")

    def test_confirmation_resend_limits(self):
        consume(self.site, "resend", "guest@example.invalid", "127.0.0.1")
        with self.assertRaises(DomainError):
            consume(self.site, "resend", "guest@example.invalid", "127.0.0.2")

    def test_untrusted_forwarded_header_is_ignored(self):
        request = RequestFactory().get(
            "/", REMOTE_ADDR="192.0.2.2", HTTP_X_FORWARDED_FOR="203.0.113.1"
        )
        self.assertEqual(client_ip(request, self.site), "192.0.2.2")

    @override_settings(COMMENTAIL={"default": {"TRUSTED_PROXIES": ["192.0.2.0/24"]}})
    def test_proxy_chain_and_spoofed_prefix(self):
        request = RequestFactory().get(
            "/",
            REMOTE_ADDR="192.0.2.2",
            HTTP_X_FORWARDED_FOR="198.51.100.1, 203.0.113.1, 192.0.2.3",
        )
        self.assertEqual(client_ip(request, self.site), "203.0.113.1")

    @override_settings(COMMENTAIL={"default": {"TRUSTED_PROXIES": ["192.0.2.0/24"]}})
    def test_malformed_trusted_header_fails_closed(self):
        request = RequestFactory().get(
            "/", REMOTE_ADDR="192.0.2.2", HTTP_X_FORWARDED_FOR="invalid"
        )
        with self.assertRaises(DomainError):
            client_ip(request, self.site)
