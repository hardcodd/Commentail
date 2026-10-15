"""Rolling site-wide limits and explicit trusted-proxy address extraction."""

import ipaddress
from datetime import timedelta
from typing import Literal

from django.db import transaction
from django.db.models import F
from django.http import HttpRequest
from django.utils import timezone
from wagtail.models import Site

from .config import technical_settings
from .models import RateEvent
from .security import digest
from .services import DomainError


def client_ip(request: HttpRequest, site: Site) -> str:
    """Discard forwarded prefixes beyond the nearest untrusted proxy hop."""
    try:
        remote = ipaddress.ip_address(request.META.get("REMOTE_ADDR", ""))
        trusted = [
            ipaddress.ip_network(item)
            for item in technical_settings(site)["TRUSTED_PROXIES"]
        ]

        def is_trusted(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
            return any(address in network for network in trusted)

        if not is_trusted(remote) or not request.META.get("HTTP_X_FORWARDED_FOR"):
            return str(remote)
        hops = [
            ipaddress.ip_address(part.strip())
            for part in request.META["HTTP_X_FORWARDED_FOR"].split(",")
        ]
        current = remote
        for address in reversed(hops):
            if not is_trusted(current):
                break
            current = address
        return str(current)
    except ValueError as exc:
        raise DomainError("Cannot determine client address") from exc


@transaction.atomic
def consume(
    site: Site, kind: Literal["comment", "resend", "captcha"], author: str, ip: str
) -> None:
    """Count author and IP together, or reject without spending either quota.

    A no-change UPDATE locks the existing Site row before reading the ledger,
    making quotas shared across pages and serializing decisions on SQLite too.
    Prune old entries through the background cleanup command, not per request.
    """
    if kind not in {"comment", "resend", "captcha"}:
        raise DomainError("Unknown rate limit")
    if not Site.objects.filter(pk=site.pk).update(port=F("port")):
        raise DomainError("Site does not exist")
    options = technical_settings(site)
    now = timezone.now()
    ip_kind = kind + "_ip"
    author_kind = kind + "_author"

    def count(event_kind: str, subject: str, seconds: int) -> int:
        return RateEvent.objects.filter(
            site=site,
            kind=event_kind,
            subject_digest=digest(subject),
            created_at__gt=now - timedelta(seconds=seconds),
        ).count()

    ip_limit = options[
        {
            "comment": "IP_LIMIT_PER_HOUR",
            "resend": "RESEND_IP_LIMIT_PER_HOUR",
            "captcha": "CAPTCHA_IP_LIMIT_PER_HOUR",
        }[kind]
    ]
    if count(ip_kind, ip, 3600) >= ip_limit:
        raise DomainError("IP limit exceeded")
    if kind == "captcha":
        if count(ip_kind, ip, 60) >= options["CAPTCHA_IP_LIMIT_PER_MINUTE"]:
            raise DomainError("Captcha limit exceeded")
    else:
        prefix = "AUTHOR" if kind == "comment" else "RESEND"
        if (
            count(author_kind, author, options[prefix + "_MIN_INTERVAL"])
            or count(author_kind, author, 3600) >= options[prefix + "_LIMIT_PER_HOUR"]
        ):
            raise DomainError("Author limit exceeded")
        RateEvent.objects.create(
            site=site, kind=author_kind, subject_digest=digest(author)
        )
    RateEvent.objects.create(site=site, kind=ip_kind, subject_digest=digest(ip))
