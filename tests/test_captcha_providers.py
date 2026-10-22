import io
import json
from unittest.mock import patch
from urllib.parse import parse_qs

from django.test import RequestFactory, SimpleTestCase, override_settings
from wagtail.models import Site

from commentail.captcha_providers import (
    GoogleRecaptcha,
    ProviderUnavailable,
    YandexSmartCaptcha,
)


@override_settings(
    ALLOWED_HOSTS=["example.com"],
    COMMENTAIL={
        "default": {
            "CAPTCHA_OPTIONS": {
                "site_key": "public",
                "secret_key": "private",
                "timeout": 3,
            }
        }
    },
)
class ProviderTests(SimpleTestCase):
    def setUp(self):
        self.request = RequestFactory().post("/", HTTP_HOST="example.com")
        self.site = Site(hostname="example.com")

    def verify(self, backend, response, token="proof"):
        with patch(
            "commentail.captcha_providers.urlopen",
            return_value=io.BytesIO(json.dumps(response).encode()),
        ) as call:
            result = backend.verify(self.request, self.site, "local-id", token)
        return result, call

    def test_google_checks_host_and_boolean_success(self):
        result, call = self.verify(
            GoogleRecaptcha(), {"success": True, "hostname": "example.com"}
        )
        self.assertTrue(result)
        data = parse_qs(call.call_args.args[0].data.decode())
        self.assertEqual(data, {"secret": ["private"], "response": ["proof"]})
        self.assertEqual(call.call_args.kwargs["timeout"], 3)
        for payload in (
            {"success": True, "hostname": "other.com"},
            {"success": False, "hostname": "example.com"},
        ):
            self.assertFalse(self.verify(GoogleRecaptcha(), payload)[0])

    def test_malformed_or_failed_transport_is_unavailable(self):
        for backend, payload in (
            (GoogleRecaptcha(), {"success": "true"}),
            (GoogleRecaptcha(), {}),
            (YandexSmartCaptcha(), {"status": "unknown"}),
        ):
            with self.assertRaises(ProviderUnavailable):
                self.verify(backend, payload)
        for backend in (GoogleRecaptcha(), YandexSmartCaptcha()):
            for error in (TimeoutError(), OSError("Synthetic transport failure")):
                with (
                    patch("commentail.captcha_providers.urlopen", side_effect=error),
                    self.assertRaises(ProviderUnavailable),
                ):
                    backend.verify(self.request, self.site, "local-id", "proof")
            for raw in (b"not-json", b"[]", b"x" * 16385):
                with (
                    patch(
                        "commentail.captcha_providers.urlopen",
                        return_value=io.BytesIO(raw),
                    ),
                    self.assertRaises(ProviderUnavailable),
                ):
                    backend.verify(self.request, self.site, "local-id", "proof")

    def test_yandex_request_uses_its_own_token_parameter(self):
        result, call = self.verify(
            YandexSmartCaptcha(), {"status": "ok", "host": "example.com"}
        )
        self.assertTrue(result)
        self.assertEqual(
            parse_qs(call.call_args.args[0].data.decode()),
            {"secret": ["private"], "token": ["proof"]},
        )

    def test_yandex_rejects_empty_host_and_checks_port(self):
        for host, expected in (
            ("example.com", True),
            ("", False),
            ("other.com", False),
            ("example.com:8080", False),
        ):
            self.assertEqual(
                self.verify(YandexSmartCaptcha(), {"status": "ok", "host": host})[0],
                expected,
            )

    def test_empty_or_oversized_token_never_contacts_provider(self):
        for backend in (GoogleRecaptcha(), YandexSmartCaptcha()):
            for token in ("", "x" * 16385):
                _, call = self.verify(backend, {}, token)
                call.assert_not_called()

    def test_public_task_does_not_expose_secret(self):
        for backend in (GoogleRecaptcha(), YandexSmartCaptcha()):
            task = backend.create(self.request, self.site)
            self.assertNotIn("private", str(task))
            self.assertEqual(task.data["site_key"], "public")
