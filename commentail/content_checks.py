"""Guest content review signals; no URL fetching or historical body scans."""

import logging
import re
import unicodedata
from datetime import timedelta

from django.db.models import F, QuerySet
from django.utils import timezone
from django.utils.crypto import salted_hmac
from wagtail.models import Site

from .config import technical_settings
from .models import Discussion, RateEvent

LINK = re.compile(r"(?<![\w@])(?:https?://|www\.)[^\s<>]+", re.IGNORECASE)


def lock_site(discussions: QuerySet[Discussion]) -> None:
    """Lock Site before discussion, serializing guest content checks across pages.

    Call inside the acceptance transaction, before reading dependent state. The
    first statement is a write so SQLite also serializes competing decisions.
    """
    Site.objects.filter(pk__in=discussions.values("site_id")).update(port=F("port"))


def normalized_text(text: str) -> str:
    """Normalize comparisons only; retain punctuation and the submitted body."""
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return " ".join(
        "".join(c for c in normalized if unicodedata.category(c) != "Cf").split()
    )


def check_and_record(
    site: Site, text: str, *, prior_text: str | None = None
) -> list[str]:
    """Review link bursts and recently accepted guest duplicates in this Site.

    A caller must hold the Site lock and roll back this ledger write if accepting
    the comment/revision fails. Only keyed fingerprints are retained; existing
    comments are not backfilled. No-op edits do not extend the duplicate window.
    """
    options = technical_settings(site)
    normalized = normalized_text(text)
    same_text = prior_text is not None and normalized == normalized_text(prior_text)
    link_count = sum(1 for _ in LINK.finditer(text))
    if same_text and link_count == sum(1 for _ in LINK.finditer(prior_text)):
        return []

    signals = []
    threshold = options["GUEST_LINK_REVIEW_THRESHOLD"]
    if threshold and link_count >= threshold:
        signals.append("many_links")

    window = options["GUEST_DUPLICATE_WINDOW_SECONDS"]
    if (
        not same_text
        and window
        and len(normalized) >= options["GUEST_DUPLICATE_MIN_LENGTH"]
    ):
        fingerprint = salted_hmac(
            "commentail.content", normalized, algorithm="sha256"
        ).hexdigest()
        if RateEvent.objects.filter(
            site=site,
            kind="content",
            subject_digest=fingerprint,
            created_at__gt=timezone.now() - timedelta(seconds=window),
        ).exists():
            signals.append("duplicate_text")
        RateEvent.objects.create(site=site, kind="content", subject_digest=fingerprint)
    if signals:
        logging.getLogger("commentail.antispam").info(
            "Guest content flagged for review",
            extra={"site_id": site.pk, "signal_codes": signals},
        )
    return signals
