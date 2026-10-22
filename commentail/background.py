"""Public maintenance entry point for a host project's periodic task queue."""

from datetime import timedelta
from typing import TypedDict

from django.db import transaction
from django.db.models import Model, QuerySet
from django.db.transaction import TransactionManagementError
from django.utils import timezone

from .limits import retention_seconds
from .models import CaptchaChallenge, FormTicket, GuestGrant, RateEvent
from .outbox import process_mail
from .services import cleanup_unconfirmed

CLEANUP_BATCH_SIZE = 500


def _delete_expired(records: QuerySet[Model]) -> None:
    """Commit bounded deletes, retaining the expiry filter if a record changes.

    Materialize primary-key batches before deleting so SQLite has no open read
    cursor or read transaction to upgrade. Keyset traversal works for UUID and
    integer keys; each batch commits before the next one is selected.
    """
    cursor = None
    while True:
        remaining = records if cursor is None else records.filter(pk__gt=cursor)
        identifiers = list(
            remaining.order_by("pk").values_list("pk", flat=True)[:CLEANUP_BATCH_SIZE]
        )
        if not identifiers:
            return
        with transaction.atomic(using=records.db):
            records.filter(pk__in=identifiers).delete()
        cursor = identifiers[-1]


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
    Expired CAPTCHA, grants, form tickets and rate events are deleted in batches
    of at most 500, each independently committed, with one fixed cleanup cutoff.
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
    _delete_expired(CaptchaChallenge.objects.filter(expires_at__lte=now))
    _delete_expired(GuestGrant.objects.filter(expires_at__lte=now))
    _delete_expired(FormTicket.objects.filter(expires_at__lte=now))
    _delete_expired(
        RateEvent.objects.filter(
            created_at__lt=now - timedelta(seconds=retention_seconds())
        )
    )
    return {"sent": sent, "removed": removed}
