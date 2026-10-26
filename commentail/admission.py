"""Request authorization boundary shared by the server-rendered form endpoints.

Do not bypass this boundary with direct calls to trusted domain services.
Views must still enforce POST and CSRF through Django middleware/decorators.
"""

import logging
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.base_user import AbstractBaseUser
from django.db import transaction
from django.db.models import F
from django.http import HttpRequest
from django.utils import timezone
from wagtail.models import Site

from .antispam import captcha_required, consume_attempt, form_signals, request_signals
from .config import technical_settings
from .email import email_configured
from .fingerprints import fingerprint_candidates
from .limits import client_ip, consume
from .models import Access, Comment, Discussion, FormTicket, Mode, SubmissionRecord
from .page_access import site_page_paths
from .policies import editorial_settings, email_enabled
from .security import digest, remembered_guest, verify_captcha
from .services import DomainError, _text, confirm_email, submit_once
from .validation import valid_identifier


def session_digest(request: HttpRequest) -> str:
    """Create the browser session if needed and return its non-reversible binding."""
    if not request.session.session_key:
        request.session.create()
    return digest(request.session.session_key)


def can_view(request: HttpRequest, discussion: Discussion) -> bool:
    """Recheck current Page restrictions or explicit object-adapter access."""
    if not discussion.page_id:
        from .objects import ObjectAccessError, checked_site, target_for

        try:
            return (
                checked_site(target_for(discussion), request).pk == discussion.site_id
            )
        except ObjectAccessError:
            return False
    page = discussion.page
    return (
        page.live
        and page.path.startswith(site_page_paths(discussion.site))
        and all(
            restriction.accept_request(request)
            for restriction in page.get_view_restrictions()
        )
    )


def issue_form(
    request: HttpRequest,
    discussion: Discussion,
    *,
    previous_key: str = "",
    previous_id: str = "",
) -> str:
    """Issue a fresh ticket, retaining age only from a live browser-owned form.

    Refresh and validation recovery must not classify an already-written draft
    as newly composed. Never accept a client timestamp or another form's age.
    """
    if not can_view(request, discussion):
        raise DomainError("Page access is required")
    consume(discussion.site, "form", "", client_ip(request, discussion.site))
    session = session_digest(request)
    now = timezone.now()
    prior = FormTicket.objects.filter(
        discussion=discussion, session_digest=session, expires_at__gt=now
    ).exclude(
        digest__in=SubmissionRecord.objects.filter(discussion=discussion).values(
            "key_digest"
        )
    )
    if previous_key:
        prior = prior.filter(digest=digest(previous_key))
    elif valid_identifier(previous_id):
        prior = prior.filter(pk=int(previous_id))
    else:
        prior = prior.none()
    started = prior.values_list("issued_at", flat=True).first()
    secret = secrets.token_urlsafe(32)
    FormTicket.objects.create(
        digest=digest(secret),
        discussion=discussion,
        session_digest=session,
        issued_at=started or now,
        expires_at=now
        + timedelta(seconds=technical_settings(discussion.site)["FORM_TICKET_SECONDS"]),
    )
    return secret


def _prepare(
    request: HttpRequest, discussion_id: int, key: str, guest_email: str
) -> tuple[Discussion, FormTicket, AbstractBaseUser | None, bool, bool]:
    """Check current access and proof context before work, then again before saving."""
    site = Site.find_for_request(request)
    if site is None:
        raise DomainError("Site cannot be determined")
    discussion = (
        Discussion.objects.select_related("site", "page")
        .filter(pk=discussion_id, site=site)
        .first()
    )
    if discussion is None or not can_view(request, discussion):
        raise DomainError("Page access is required")
    options = editorial_settings(discussion)
    if options.mode != Mode.OPEN:
        raise DomainError("Discussion is closed")
    ticket = FormTicket.objects.filter(
        digest=digest(key),
        discussion=discussion,
        session_digest=session_digest(request),
        expires_at__gt=timezone.now(),
    ).first()
    if ticket is None:
        raise DomainError("Invalid or expired form")
    user = request.user if request.user.is_authenticated else None
    if user is not None and not user.is_active:
        raise DomainError("Account cannot comment")
    if (
        options.access == Access.NONE
        or (user is None and options.access == Access.REGISTERED)
        or (user is not None and options.access == Access.GUESTS)
    ):
        raise DomainError("Author cannot comment")
    mail_available = email_enabled(site.pk) and email_configured()
    if user is None and not mail_available:
        raise DomainError("Guest comments require configured email delivery")
    subscribe = mail_available and bool(
        guest_email.strip() if user is None else getattr(user, "email", "")
    )
    grant = (
        remembered_guest(request.COOKIES.get(f"commentail_guest_{site.pk}", ""), site)
        if user is None
        else None
    )
    remembered = (
        grant is not None
        and grant.email.strip().casefold() == guest_email.strip().casefold()
    )
    return discussion, ticket, user, remembered, subscribe


def accept_request(
    request: HttpRequest,
    discussion_id: int,
    key: str,
    *,
    text: str,
    guest_name: str = "",
    guest_email: str = "",
    reply_to: int | None = None,
    challenge_id: str = "",
    answer: str = "",
    subscribe: bool = False,
    honeypot: str = "",
) -> Comment:
    """Admit one submission, with durable attempt budgets before expensive proofs.

    External verification never holds the Site quota lock. Access/ticket/policy
    are rechecked after verification. A consumed proof is not restored after a
    later validation error: the returned form supplies a fresh challenge.
    """
    discussion, ticket, user, remembered, subscribe = _prepare(
        request, discussion_id, key, guest_email
    )
    site = discussion.site
    actor = (
        "user:" + str(user.pk)
        if user is not None
        else "guest:" + guest_email.strip().casefold()
    )

    def recorded() -> bool:
        return SubmissionRecord.objects.filter(
            discussion=discussion,
            actor_digest__in=fingerprint_candidates(
                actor, f"submission.actor.{discussion.pk}"
            ),
            key_digest=digest(key),
        ).exists()

    def save(*, suspicious: bool = False) -> Comment:
        return submit_once(
            discussion.pk,
            key,
            text=text,
            user=user,
            guest_name=guest_name,
            guest_email=guest_email,
            reply_to=reply_to,
            subscribe=subscribe,
            suspicious=suspicious,
            language=getattr(request, "LANGUAGE_CODE", settings.LANGUAGE_CODE),
        )

    if recorded():
        return save()
    if user is None:
        consume_attempt(request, site, client_ip(request, site))
    _text(text, editorial_settings(discussion))
    backend = technical_settings(site)["CAPTCHA_BACKEND"]
    proved = False
    if user is None and captcha_required(request, site, remembered):
        proved = verify_captcha(request, site, challenge_id, answer)
        if not proved:
            logging.getLogger("commentail.antispam").info(
                "Guest proof refused", extra={"site_id": site.pk, "signal": "captcha"}
            )
            raise DomainError("Incorrect or expired CAPTCHA")

    with transaction.atomic():
        Site.objects.filter(pk=site.pk).update(port=F("port"))
        discussion, ticket, user, remembered, subscribe = _prepare(
            request, discussion_id, key, guest_email
        )
        if recorded():
            return save()
        if (
            user is None
            and captcha_required(request, site, remembered)
            and (not proved or technical_settings(site)["CAPTCHA_BACKEND"] != backend)
        ):
            raise DomainError("Incorrect or expired CAPTCHA")
        consume(site, "comment", actor, client_ip(request, site))
        signals = (
            request_signals(request, site) + form_signals(ticket, site, honeypot)
            if user is None
            else []
        )
        result = save(suspicious=bool(signals))
        if signals:
            result.spam_signals = list(dict.fromkeys(result.spam_signals + signals))
            result.save(update_fields=["spam_signals"])
            logging.getLogger("commentail.antispam").info(
                "Guest comment flagged for review",
                extra={"site_id": site.pk, "signal_codes": signals},
            )
        if user is None and remembered:
            result = confirm_email(result.pk)
    return result
