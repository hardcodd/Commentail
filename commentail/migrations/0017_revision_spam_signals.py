"""Retain private content-check reasons on guest author proposals."""

from typing import ClassVar

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies: ClassVar[list] = [
        ("commentail", "0016_guest_antispam"),
    ]

    operations: ClassVar[list] = [
        migrations.AddField(
            model_name="commentrevision",
            name="spam_signals",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
