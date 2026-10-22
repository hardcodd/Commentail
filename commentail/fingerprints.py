"""Keyed, purpose-scoped fingerprints for predictable private values.

Wrap SHA-256 rather than plaintext so an upgrade can protect existing records
without recovering email, IP or submitted payloads. Random capability hashes
remain separate. Retain old keys in SECRET_KEY_FALLBACKS while their records live.
"""

import hashlib

from django.conf import settings
from django.utils.crypto import salted_hmac


def _fingerprint(value: str, purpose: str, key: str) -> str:
    hashed = hashlib.sha256(value.encode()).hexdigest()
    return salted_hmac(
        "commentail.fingerprint." + purpose, hashed, secret=key, algorithm="sha256"
    ).hexdigest()


def fingerprint(value: str, purpose: str) -> str:
    """Return the current key's fingerprint; purpose includes its owning scope."""
    return _fingerprint(value, purpose, settings.SECRET_KEY)


def fingerprint_candidates(value: str, purpose: str) -> list[str]:
    """Match current and explicitly retained fallback keys, never unkeyed hashes."""
    return list(
        dict.fromkeys(
            _fingerprint(value, purpose, key)
            for key in (settings.SECRET_KEY, *settings.SECRET_KEY_FALLBACKS)
        )
    )
