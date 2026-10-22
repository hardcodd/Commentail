"""Recipient address and target eligibility evaluated again before delivery."""

from dataclasses import dataclass
from datetime import datetime

from django.db.models import Model
from django.utils.module_loading import import_string

from .config import technical_settings
from .models import Comment
from .services import DomainError


@dataclass(frozen=True)
class GuestRecipient:
    """Restricted callback input; no comment body, model traversal or user account."""

    email: str
    name: str
    confirmed_at: datetime | None


def _email(recipient: Comment) -> str:
    if recipient.account_deleted:
        return ""
    if recipient.user_id:
        return (
            str(getattr(recipient.user, "email", "") or "")
            if recipient.user.is_active
            else ""
        )
    return recipient.email


def _can_receive(recipient: Comment) -> bool:
    """Recheck target access without assuming browser password/session proof.

    Restricted guests require the explicit host callback. Adapter failures
    raise DomainError so the worker records a failed job instead of granting access."""
    from .objects import ObjectAccessError, ObjectAdapterError, checked_site, target_for

    if not recipient.discussion.page_id:
        try:
            target = target_for(recipient.discussion)
            from django.contrib.auth.models import AnonymousUser
            from django.contrib.sessions.backends.base import SessionBase
            from django.http import HttpRequest

            request = HttpRequest()
            request.method = "GET"
            site = recipient.discussion.site
            request.META.update(
                HTTP_HOST=site.hostname,
                SERVER_NAME=site.hostname,
                SERVER_PORT=str(site.port),
            )
            request.user = recipient.user if recipient.user_id else AnonymousUser()
            request.session = SessionBase()
            request.LANGUAGE_CODE = recipient.language
            checked_site(
                target, request, view=bool(recipient.user_id), expected_site=site
            )
            if recipient.user_id:
                return recipient.user.is_active
        except ObjectAdapterError as exc:
            raise DomainError("Object mail access handler failed") from exc
        except ObjectAccessError:
            return False
        return _guest_can_receive(recipient, target)
    page = recipient.discussion.page
    if not page.live:
        return False
    restrictions = list(page.get_view_restrictions())
    if not restrictions:
        return True
    if recipient.user_id:
        user = recipient.user
        for rule in restrictions:
            if rule.restriction_type == rule.LOGIN and not user.is_active:
                return False
            if rule.restriction_type == rule.GROUPS and not (
                user.is_superuser or rule.groups.filter(user=user).exists()
            ):
                return False
            if rule.restriction_type == rule.PASSWORD:
                return False  # A mail worker cannot prove browser password entry.
        return True
    return _guest_can_receive(recipient, page.specific)


def _guest_can_receive(recipient: Comment, target: Model) -> bool:
    """Require an explicit True from the host; callback failures become job errors."""
    path = technical_settings(recipient.discussion.site)["CAN_SEND_GUEST_EMAIL"]
    if not path:
        return False
    callback = import_string(path)
    try:
        return (
            callback(
                GuestRecipient(
                    recipient.email, recipient.guest_name, recipient.email_confirmed_at
                ),
                target,
                recipient.discussion.site,
            )
            is True
        )
    except Exception as exc:
        # An extension failure is an explicit job error, never a permission grant.
        raise DomainError("Guest mail access handler failed") from exc
