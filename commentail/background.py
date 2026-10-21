"""Public maintenance entry point for a host project's periodic task queue."""

from datetime import timedelta
from typing import TypedDict

from django.db import transaction
from django.db.transaction import TransactionManagementError
from django.utils import timezone

from .models import CaptchaChallenge, FormTicket, GuestGrant, RateEvent
from .outbox import process_mail
from .services import cleanup_unconfirmed


class ProcessingResult(TypedDict):
    """Backend-accepted mail and expired unconfirmed comments removed by this run."""

    sent: int
    removed: int


def process_pending(*, mail_limit: int = 100) -> ProcessingResult:
    """Run one maintenance pass outside a caller transaction; return JSON-safe counts.

    Schedule once per minute through the host queue or process_commentail command.
    A positive mail_limit bounds due mail claims, not the cleanup work. The database
    outbox retains leases, retry timing, access checks and original link deadlines;
    repeated task execution does not resend jobs already marked sent. Transport
    acceptance is not evidence of inbox delivery. Unexpected errors propagate to
    the scheduler; earlier completed work is not rolled back as a single batch.
    """
    if type(mail_limit) is not int or mail_limit <= 0:
        raise ValueError("mail_limit must be a positive integer")
    if not transaction.get_autocommit():
        raise TransactionManagementError(
            "Run Commentail background processing outside a transaction"
        )
    removed = cleanup_unconfirmed()
    sent = process_mail(limit=mail_limit)
    now = timezone.now()
    CaptchaChallenge.objects.filter(expires_at__lte=now).delete()
    GuestGrant.objects.filter(expires_at__lte=now).delete()
    FormTicket.objects.filter(expires_at__lte=now).delete()
    RateEvent.objects.filter(created_at__lt=now - timedelta(hours=1)).delete()
    return {"sent": sent, "removed": removed}
