"""Server-side proof primitives; secrets are opaque and purpose/site scoped."""

import hashlib
import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal, Protocol
from uuid import UUID

from django.db import transaction
from django.db.models import F
from django.http import HttpRequest
from django.template.loader import get_template
from django.utils import timezone
from django.utils.crypto import salted_hmac
from django.utils.module_loading import import_string
from django.utils.translation import gettext as _
from wagtail.models import Site

from .config import technical_settings
from .models import ActionToken, CaptchaChallenge, Comment, GuestGrant
from .services import DomainError

Purpose = Literal["confirm", "edit", "view", "unsubscribe"]


def digest(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def issue_token(comment: Comment, purpose: Purpose, expires_at: datetime) -> str:
    """Return a secret once; persist only its hash. Never log the return value."""
    if purpose not in {"confirm", "edit", "view", "unsubscribe"}:
        raise DomainError("Unknown token purpose")
    token = ActionToken(comment=comment, purpose=purpose, expires_at=expires_at)
    secret = token_secret(token)
    token.digest = digest(secret)
    token.save()
    return secret


def token_secret(token: ActionToken) -> str:
    """Reconstruct queued links without storing a plaintext capability in the DB.

    The random nonce is public state; deriving the secret requires SECRET_KEY.
    Rotating that key prevents regeneration of old links for pending jobs.
    """
    return salted_hmac(
        "commentail.action", str(token.nonce) + ":" + token.purpose, algorithm="sha256"
    ).hexdigest()


def verify_token(secret: str, purpose: Purpose, site: Site) -> ActionToken:
    """Read-only verification: GET must not confirm, unsubscribe or change state."""
    token = (
        ActionToken.objects.filter(
            digest=digest(secret),
            purpose=purpose,
            comment__discussion__site=site,
            expires_at__gt=timezone.now(),
        )
        .select_related("comment")
        .first()
    )
    if token is None:
        raise DomainError("Invalid or expired link")
    return token


def remember_guest(
    site: Site, email: str, *, confirmed_at: datetime | None = None
) -> str:
    """Issue only after email proof. Browsing/submission never renew this grant."""
    secret = secrets.token_urlsafe(32)
    now = confirmed_at or timezone.now()
    GuestGrant.objects.create(
        digest=digest(secret),
        site=site,
        email=email,
        confirmed_at=now,
        expires_at=now
        + timedelta(seconds=technical_settings(site)["GUEST_GRANT_SECONDS"]),
    )
    return secret


def remembered_guest(secret: str, site: Site) -> GuestGrant | None:
    return GuestGrant.objects.filter(
        digest=digest(secret), site=site, expires_at__gt=timezone.now()
    ).first()


@dataclass(frozen=True)
class CaptchaTask:
    id: UUID | str
    template: str
    data: dict[str, str]


class ArithmeticCaptcha:
    """Replaceable backend. Answers remain in the DB and are tied to the session."""

    def _session(self, request: HttpRequest) -> str:
        if not request.session.session_key:
            request.session.create()
        return digest(request.session.session_key)

    @transaction.atomic
    def create(self, request: HttpRequest, site: Site) -> CaptchaTask:
        session_digest = self._session(request)
        # Invalidate every older task from this session/site on refresh.
        CaptchaChallenge.objects.filter(
            site=site, session_digest=session_digest, used=False
        ).update(used=True)
        left, right = secrets.randbelow(9) + 1, secrets.randbelow(9) + 1
        challenge = CaptchaChallenge.objects.create(
            site=site,
            session_digest=session_digest,
            answer=left + right,
            expires_at=timezone.now()
            + timedelta(seconds=technical_settings(site)["CAPTCHA_SECONDS"]),
        )
        return CaptchaTask(
            challenge.pk,
            "commentail/captcha.html",
            {"question": f"{left} + {right} = ?"},
        )

    @transaction.atomic
    def verify(
        self, request: HttpRequest, site: Site, challenge_id: UUID | str, answer: str
    ) -> bool:
        try:
            identifier = UUID(str(challenge_id))
        except (ValueError, TypeError, AttributeError):
            return False
        query = CaptchaChallenge.objects.filter(
            pk=identifier,
            site=site,
            session_digest=self._session(request),
            used=False,
            expires_at__gt=timezone.now(),
            attempts__lt=technical_settings(site)["CAPTCHA_ATTEMPTS"],
        )
        # Claim this attempt by a write before reading. Every attempt counts;
        # accepting an answer also consumes the challenge in this transaction.
        if not query.update(attempts=F("attempts") + 1):
            return False
        challenge = CaptchaChallenge.objects.get(pk=identifier)
        try:
            correct = int(answer.strip()) == challenge.answer
        except (ValueError, AttributeError):
            correct = False
        if correct:
            CaptchaChallenge.objects.filter(pk=identifier).update(used=True)
        return correct


@transaction.atomic
def confirm_from_token(secret: str, site: Site) -> Comment:
    """Explicit action only. GET link verification must call verify_token instead."""
    from .services import confirm_email

    token = verify_token(secret, "confirm", site)
    comment = confirm_email(token.comment_id)
    ActionToken.objects.filter(pk=token.pk, used_at__isnull=True).update(
        used_at=timezone.now()
    )
    return comment


@transaction.atomic
def unsubscribe(secret: str, site: Site) -> bool:
    """Disable only this comment's subscription; repetition has no new effect."""
    from .models import ReplySubscription

    token = verify_token(secret, "unsubscribe", site)
    changed = ReplySubscription.objects.filter(
        comment_id=token.comment_id, enabled=True
    ).update(enabled=False)
    ActionToken.objects.filter(pk=token.pk, used_at__isnull=True).update(
        used_at=timezone.now()
    )
    return bool(changed)


class CaptchaBackend(Protocol):
    def create(self, request: HttpRequest, site: Site) -> CaptchaTask: ...
    def verify(
        self, request: HttpRequest, site: Site, challenge_id: str, answer: str
    ) -> bool: ...


def create_captcha(request: HttpRequest, site: Site) -> CaptchaTask:
    """Issue a rate-limited challenge with library-owned proof constraints."""
    from .limits import client_ip, consume

    consume(site, "captcha", "", client_ip(request, site))
    path = technical_settings(site)["CAPTCHA_BACKEND"]
    if path is None:
        return ArithmeticCaptcha().create(request, site)
    try:
        backend: CaptchaBackend = import_string(path)()
        task = backend.create(request, site)
        if (
            not isinstance(task, CaptchaTask)
            or not isinstance(task.id, (str, UUID))
            or not 0 < len(str(task.id)) <= 255
            or not isinstance(task.template, str)
            or not isinstance(task.data, dict)
            or not all(
                isinstance(key, str) and isinstance(value, str)
                for key, value in task.data.items()
            )
        ):
            raise ValueError("Invalid CAPTCHA task contract")
        get_template(task.template)
        with transaction.atomic():
            session = ArithmeticCaptcha()._session(request)
            CaptchaChallenge.objects.filter(
                site=site, session_digest=session, used=False
            ).update(used=True)
            challenge = CaptchaChallenge.objects.create(
                site=site,
                session_digest=session,
                answer=0,
                backend=path,
                provider_id=str(task.id),
                expires_at=timezone.now()
                + timedelta(seconds=technical_settings(site)["CAPTCHA_SECONDS"]),
            )
        return CaptchaTask(challenge.pk, task.template, task.data)
    except Exception as error:
        # Backend exceptions may contain secrets: log the type, never payloads.
        logging.getLogger("commentail.captcha").error(
            "CAPTCHA creation failed (%s)", type(error).__name__
        )
        raise DomainError(
            _("CAPTCHA is unavailable. Please try again later.")
        ) from error


@transaction.atomic
def verify_captcha(
    request: HttpRequest, site: Site, challenge_id: UUID | str, answer: str
) -> bool:
    """Enforce expiry, binding and attempts even if a custom verifier accepts all."""
    path = technical_settings(site)["CAPTCHA_BACKEND"]
    if path is None:
        # Arithmetic rows never carry a provider envelope.
        try:
            if (
                CaptchaChallenge.objects.filter(pk=UUID(str(challenge_id)))
                .exclude(backend="")
                .exists()
            ):
                return False
        except (ValueError, TypeError, AttributeError):
            return False
        return ArithmeticCaptcha().verify(request, site, challenge_id, answer)
    try:
        identifier = UUID(str(challenge_id))
    except (ValueError, TypeError, AttributeError):
        return False
    query = CaptchaChallenge.objects.filter(
        pk=identifier,
        site=site,
        session_digest=ArithmeticCaptcha()._session(request),
        backend=path,
        used=False,
        expires_at__gt=timezone.now(),
        attempts__lt=technical_settings(site)["CAPTCHA_ATTEMPTS"],
    )
    if not query.update(attempts=F("attempts") + 1):
        return False
    challenge = CaptchaChallenge.objects.get(pk=identifier)
    try:
        backend: CaptchaBackend = import_string(path)()
        accepted = backend.verify(request, site, challenge.provider_id, answer)
        if type(accepted) is not bool:
            raise ValueError("CAPTCHA verification must return bool")
    except Exception as error:  # noqa: BLE001 - isolate arbitrary host backend failures
        logging.getLogger("commentail.captcha").error(
            "CAPTCHA verification failed (%s)", type(error).__name__
        )
        return False
    if accepted:
        CaptchaChallenge.objects.filter(pk=identifier, used=False).update(used=True)
    return accepted
