"""Opt-in reCAPTCHA v2 and SmartCaptcha adapters for the stable backend contract."""

import json
import secrets
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

from django.http import HttpRequest
from django.views.decorators.debug import sensitive_variables
from wagtail.models import Site

from .config import technical_settings
from .security import CaptchaTask


class ProviderUnavailable(Exception):
    """A provider transport/protocol failure, distinct from an invalid proof."""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Credentials must never follow a redirect to another endpoint.
        return None


urlopen = build_opener(_NoRedirect()).open


class _Provider:
    provider: str
    endpoint: str
    token_parameter: str
    host_field: str

    def create(self, request: HttpRequest, site: Site) -> CaptchaTask:
        """Rendering is local; only the public key reaches the browser."""
        options = technical_settings(site)["CAPTCHA_OPTIONS"]
        return CaptchaTask(
            secrets.token_urlsafe(24),
            "commentail/provider-captcha.html",
            {
                "provider": self.provider,
                "site_key": str(options["site_key"]),
            },
        )

    @sensitive_variables()
    def verify(
        self, request: HttpRequest, site: Site, challenge_id: str, answer: str
    ) -> bool:
        """Validate one token over HTTPS; reject missing/mismatched host claims.

        IP forwarding is deliberately omitted (optional in both protocols).
        Timeout, response size and redirect policy bound untrusted remote work.
        """
        if not answer or len(answer) > 16384:
            return False
        options = technical_settings(site)["CAPTCHA_OPTIONS"]
        payload = urlencode(
            {"secret": options["secret_key"], self.token_parameter: answer}
        ).encode()
        try:
            with urlopen(
                Request(
                    self.endpoint,
                    data=payload,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                ),
                timeout=options.get("timeout", 3),
            ) as response:
                raw = response.read(16385)
            if len(raw) > 16384:
                raise ValueError("Provider response too large")
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise TypeError("Invalid provider response")
        except (OSError, ValueError, TypeError) as exc:
            raise ProviderUnavailable() from exc
        host = data.get(self.host_field)
        expected = (
            request.get_host()
            if self.provider == "yandex"
            else request.get_host().split(":", 1)[0]
        )
        return (
            self._accepted(data)
            and isinstance(host, str)
            and host.casefold() == expected.casefold()
        )

    def _accepted(self, data: dict[str, object]) -> bool:
        raise NotImplementedError


class GoogleRecaptcha(_Provider):
    """Google reCAPTCHA v2 checkbox (not v3 scores or Enterprise assessments)."""

    provider = "google"
    endpoint = "https://www.google.com/recaptcha/api/siteverify"
    token_parameter = "response"
    host_field = "hostname"

    def _accepted(self, data: dict[str, object]) -> bool:
        if type(data.get("success")) is not bool:
            raise ProviderUnavailable()
        codes = data.get("error-codes", [])
        if not isinstance(codes, list) or not all(
            isinstance(code, str) for code in codes
        ):
            raise ProviderUnavailable()
        if any(
            code in {"invalid-input-secret", "missing-input-secret"} for code in codes
        ):
            raise ProviderUnavailable()
        return data.get("success") is True


class YandexSmartCaptcha(_Provider):
    """Yandex SmartCaptcha standard widget with mandatory nonempty host matching."""

    provider = "yandex"
    endpoint = "https://smartcaptcha.cloud.yandex.ru/validate"
    token_parameter = "token"
    host_field = "host"

    def _accepted(self, data: dict[str, object]) -> bool:
        if data.get("status") not in ("ok", "failed"):
            raise ProviderUnavailable()
        return data.get("status") == "ok"
