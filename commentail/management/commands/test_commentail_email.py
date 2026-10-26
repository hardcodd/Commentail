"""Send a transport probe without touching comments, tokens or queued jobs."""

from argparse import ArgumentParser
from typing import ClassVar

from django.core.exceptions import ValidationError
from django.core.mail import EmailMessage
from django.core.mail.backends.smtp import EmailBackend
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email

from commentail.email import connection, email_settings


class Command(BaseCommand):
    help = "Send one test email using Commentail's configured backend and sender."
    # The probe needs no database or unrelated application checks. Its transport
    # configuration is validated by email_settings before any network access.
    requires_system_checks: ClassVar[list[str]] = []

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("--to", required=True, help="One explicit test recipient.")

    def handle(self, *args: object, **options: object) -> None:
        recipient = options.get("to")
        try:
            validate_email(recipient)
        except (ValidationError, TypeError):
            raise CommandError("Provide one valid email address with --to.") from None

        try:
            config = email_settings()
            backend = connection()
            if isinstance(backend, EmailBackend):
                backend.timeout = (
                    30 if backend.timeout is None else min(30, backend.timeout)
                )
            with backend:
                message = EmailMessage(
                    "Commentail test email",
                    "This is a test of the email backend and sender configured for Commentail.\n"
                    "No comment or subscription was created.\n",
                    config["FROM_EMAIL"],
                    [recipient],
                    connection=backend,
                )
                accepted = message.send()
        except Exception as exc:  # noqa: BLE001 -- redact arbitrary provider failures
            # Arbitrary providers may include credentials in exceptions. Keep
            # only the class, including when Django is run with --traceback.
            raise CommandError(f"Test email failed ({type(exc).__name__}).") from None

        if accepted != 1:
            raise CommandError("The backend did not accept the test email.")
        self.stdout.write(
            "The backend accepted one test email. This does not confirm inbox delivery."
        )
