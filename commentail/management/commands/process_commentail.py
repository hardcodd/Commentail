from django.core.management.base import BaseCommand

from commentail.background import process_pending


class Command(BaseCommand):
    help = "Send queued Commentail mail and erase expired transient records. Run once per minute."

    def handle(self, *args: object, **options: object) -> None:
        result = process_pending()
        self.stdout.write(
            f"Sent {result['sent']} messages; removed {result['removed']} unconfirmed comments."
        )
