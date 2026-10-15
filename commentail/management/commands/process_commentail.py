from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from commentail.models import CaptchaChallenge, FormTicket, GuestGrant, RateEvent
from commentail.outbox import process_mail
from commentail.services import cleanup_unconfirmed


class Command(BaseCommand):
    help = "Send queued Commentail mail and erase expired transient records. Run once per minute."

    def handle(self, *args: object, **options: object) -> None:
        removed = cleanup_unconfirmed()
        sent = process_mail()
        now = timezone.now()
        CaptchaChallenge.objects.filter(expires_at__lte=now).delete()
        GuestGrant.objects.filter(expires_at__lte=now).delete()
        FormTicket.objects.filter(expires_at__lte=now).delete()
        RateEvent.objects.filter(created_at__lt=now - timedelta(hours=1)).delete()
        self.stdout.write(
            f"Sent {sent} messages; removed {removed} unconfirmed comments."
        )
