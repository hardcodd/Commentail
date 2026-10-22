"""Low-friction guest signals and durable attempt budgets, separate from content."""

import logging
from datetime import timedelta

from django.db import transaction
from django.db.models import F
from django.http import HttpRequest
from django.utils import timezone
from django.utils.translation import gettext as _
from wagtail.models import Site

from .config import technical_settings
from .models import FormTicket, RateEvent
from .security import digest
from .services import DomainError


def signal_labels(codes: list[str]) -> list[str]:
    """Translate stored diagnostic codes only in the moderator's private view."""
    labels = {
        "honeypot": _("The hidden form field was filled in."),
        "fast_form": _("The form was submitted unusually quickly."),
        "missing_user_agent": _("The browser identification header was missing."),
        "cross_site": _("The request came from another site."),
        "duplicate_text": _("The same text was recently submitted on this site."),
        "many_links": _("The link count reached the review threshold."),
    }
    return [labels[code] for code in codes if code in labels]


def request_signals(request: HttpRequest, site: Site) -> list[str]:
    """Headers are review signals, never an identity or proof of automation."""
    checks = technical_settings(site)["GUEST_REQUEST_CHECKS"]
    return [
        code
        for code, present in (
            ("missing_user_agent", not request.META.get("HTTP_USER_AGENT", "").strip()),
            ("cross_site", request.META.get("HTTP_SEC_FETCH_SITE") == "cross-site"),
        )
        if code in checks and present
    ]


def captcha_required(request: HttpRequest, site: Site, remembered: bool) -> bool:
    """Retain the usual remembered-email exemption unless risk or strict policy applies."""
    return (
        not remembered
        or technical_settings(site)["GUEST_CAPTCHA_MODE"] == "always"
        or bool(request_signals(request, site))
    )


def form_signals(ticket: FormTicket, site: Site, honeypot: str) -> list[str]:
    """Fast users and autofill are reviewed rather than blocked or silently dropped."""
    signals = ["honeypot"] if honeypot.strip() else []
    if (timezone.now() - ticket.issued_at).total_seconds() < technical_settings(site)[
        "GUEST_FORM_MIN_SECONDS"
    ]:
        signals.append("fast_form")
    return signals


@transaction.atomic
def consume_attempt(request: HttpRequest, site: Site, ip: str) -> None:
    """Commit before proof/acceptance so rejected submissions still spend a quota.

    Do not use an unverified email for this budget: that would let strangers
    exhaust a victim's quota. The session budget complements the shared IP budget.
    """
    Site.objects.filter(pk=site.pk).update(port=F("port"))
    options = technical_settings(site)
    now = timezone.now()
    session = digest(request.session.session_key)
    address = digest(ip)
    budgets = (
        ("attempt_session", session, 60, options["GUEST_ATTEMPTS_PER_MINUTE"]),
        ("attempt_ip", address, 60, options["GUEST_IP_ATTEMPTS_PER_MINUTE"]),
        ("attempt_ip", address, 3600, options["GUEST_IP_ATTEMPTS_PER_HOUR"]),
    )
    for kind, subject, seconds, limit in budgets:
        if (
            RateEvent.objects.filter(
                site=site,
                kind=kind,
                subject_digest=subject,
                created_at__gt=now - timedelta(seconds=seconds),
            ).count()
            >= limit
        ):
            logging.getLogger("commentail.antispam").info(
                "Guest attempt limited", extra={"site_id": site.pk, "signal": kind}
            )
            raise DomainError(
                _("Too many attempts. Please wait and try again. Your draft is kept.")
            )
    RateEvent.objects.bulk_create(
        [
            RateEvent(site=site, kind="attempt_session", subject_digest=session),
            RateEvent(site=site, kind="attempt_ip", subject_digest=address),
        ]
    )
