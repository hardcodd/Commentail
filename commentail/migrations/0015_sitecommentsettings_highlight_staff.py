"""Enable optional staff name highlighting for existing and new sites."""

from typing import ClassVar

from django.db import migrations, models
from django.db.migrations.operations.base import Operation


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("commentail", "0014_reading_indexes"),
    ]

    operations: ClassVar[list[Operation]] = [
        migrations.AddField(
            model_name="sitecommentsettings",
            name="highlight_staff",
            field=models.BooleanField(default=True),
        ),
    ]
