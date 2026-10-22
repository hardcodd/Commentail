"""Request authorization boundary shared by the server-rendered form endpoints.

Do not bypass this boundary with direct calls to trusted domain services.
Views must still enforce POST and CSRF through Django middleware/decorators.
"""

import secrets
from datetime import timedelta

from django.conf import settings
from django.core.mail.backends.smtp import EmailBackend
from django.db import transaction
from django.db.models import F
from django.http import HttpRequest
from django.utils import timezone
from django.utils.module_loading import import_string
from wagtail.models import Site

from .config import technical_settings
from .limits import client_ip, consume
from .models import Access, Comment, Discussion, FormTicket, Mode, SubmissionRecord
from .policies import editorial_settings, email_enabled
from .security import digest, remembered_guest, verify_captcha
from .services import DomainError, _text, confirm_email, submit_once


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
    return page.live and all(
        restriction.accept_request(request)
        for restriction in page.get_view_restrictions()
    )


def email_configured() -> bool:
    """Check configuration without constructing or contacting the transport.

    Only SMTP needs an explicit host; other Django backends own their settings.
    This is availability for forms, not evidence of successful delivery.
    """
    backend = import_string(settings.EMAIL_BACKEND)
    if issubclass(backend, EmailBackend):
        return settings.is_overridden("EMAIL_HOST") and bool(settings.EMAIL_HOST)
    return True


def issue_form(request: HttpRequest, discussion: Discussion) -> str:
    """Persist a bounded-life session/Site-bound form ticket after target access."""
    if not can_view(request, discussion):
        raise DomainError("Page access is required")
    secret = secrets.token_urlsafe(32)
    FormTicket.objects.create(
        digest=digest(secret),
        discussion=discussion,
        session_digest=session_digest(request),
        expires_at=timezone.now()
        + timedelta(seconds=technical_settings(discussion.site)["FORM_TICKET_SECONDS"]),
    )
    return secret


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
) -> Comment:
    """Validate access on every attempt, including already-accepted form replays.

    Incorrect CAPTCHA attempts commit before DomainError is raised, so the
    attempts counter cannot be reset by rolling back a rejected submission.
    A successful CAPTCHA and accepted comment share a transaction.
    """
    site = Site.find_for_request(request)
    if site is None:
        raise DomainError("Site cannot be determined")
    failure = None
    result = None
    with transaction.atomic():
        # Lock site-wide quotas before any reads in this admission transaction.
        if not Site.objects.filter(pk=site.pk).update(port=F("port")):
            raise DomainError("Site does not exist")
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
        subscribe = mail_available and bool(
            guest_email.strip() if user is None else getattr(user, "email", "")
        )
        if user is None and not mail_available:
            raise DomainError("Guest comments require configured email delivery")

        actor = (
            "user:" + str(user.pk)
            if user is not None
            else "guest:" + guest_email.strip().casefold()
        )
        if SubmissionRecord.objects.filter(
            discussion=discussion, actor_digest=digest(actor), key_digest=digest(key)
        ).exists():
            return submit_once(
                discussion.pk,
                key,
                text=text,
                user=user,
                guest_name=guest_name,
                guest_email=guest_email,
                reply_to=reply_to,
                subscribe=subscribe,
                language=getattr(request, "LANGUAGE_CODE", settings.LANGUAGE_CODE),
            )

        _text(text, options)
        grant = (
            remembered_guest(
                request.COOKIES.get(f"commentail_guest_{site.pk}", ""), site
            )
            if user is None
            else None
        )
        remembered = (
            grant is not None
            and grant.email.strip().casefold() == guest_email.strip().casefold()
        )
        if (
            user is None
            and not remembered
            and not verify_captcha(request, site, challenge_id, answer)
        ):
            failure = "Incorrect or expired CAPTCHA"
        else:
            consume(site, "comment", actor, client_ip(request, site))
            checks = technical_settings(site)["GUEST_REQUEST_CHECKS"]
            suspicious = user is None and (
                (
                    "missing_user_agent" in checks
                    and not request.META.get("HTTP_USER_AGENT", "").strip()
                )
                or (
                    "cross_site" in checks
                    and request.META.get("HTTP_SEC_FETCH_SITE") == "cross-site"
                )
            )
            result = submit_once(
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
            if user is None and remembered:
                result = confirm_email(result.pk)

    if failure:
        raise DomainError(failure)
    if result is None:
        raise DomainError("Submission was not accepted")
    return result
