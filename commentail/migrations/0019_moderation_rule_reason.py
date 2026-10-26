"""Add optional sender-facing reasons without changing existing rule choices."""

from typing import ClassVar

from django.db import migrations, models
from django.db.migrations.operations.base import Operation


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("commentail", "0018_private_fingerprints"),
    ]

    operations: ClassVar[list[Operation]] = [
        migrations.AddField(
            model_name="moderationrule",
            name="reason",
            field=models.TextField(blank=True, max_length=2000),
        ),
    ]
