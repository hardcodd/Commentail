"""Protect legacy private hashes without recovering their original values.

Stop writers and retain the same SECRET_KEY during this atomic data migration.
The keyed wrapping is intentionally irreversible; downgrade requires a backup.
Random capability/form hashes and existing keyed content signals are unchanged.
"""

from typing import ClassVar

from django.apps.registry import Apps
from django.db import migrations
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.operations.base import Operation
from django.utils.crypto import salted_hmac


def protect_fingerprints(apps: Apps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    """Rekey in bounded batches using historical models and the migration alias."""
    alias = schema_editor.connection.alias

    def wrap(hashed: str, purpose: str) -> str:
        return salted_hmac(
            "commentail.fingerprint." + purpose, hashed, algorithm="sha256"
        ).hexdigest()

    events = apps.get_model("commentail", "RateEvent").objects.using(alias)
    cursor = 0
    while batch := list(
        events.exclude(kind="content").filter(pk__gt=cursor).order_by("pk")[:500]
    ):
        for event in batch:
            event.subject_digest = wrap(
                event.subject_digest, f"rate.{event.site_id}.{event.kind}"
            )
        events.bulk_update(batch, ["subject_digest"], batch_size=500)
        cursor = batch[-1].pk

    records = apps.get_model("commentail", "SubmissionRecord").objects.using(alias)
    cursor = 0
    while batch := list(records.filter(pk__gt=cursor).order_by("pk")[:500]):
        for record in batch:
            record.actor_digest = wrap(
                record.actor_digest, f"submission.actor.{record.discussion_id}"
            )
            record.payload_digest = wrap(
                record.payload_digest, f"submission.payload.{record.discussion_id}"
            )
        records.bulk_update(batch, ["actor_digest", "payload_digest"], batch_size=500)
        cursor = batch[-1].pk


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("commentail", "0017_revision_spam_signals")
    ]
    operations: ClassVar[list[Operation]] = [migrations.RunPython(protect_fingerprints)]
