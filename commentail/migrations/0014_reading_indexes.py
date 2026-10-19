"""Index bounded publication/thread reads and time-based rate-ledger cleanup."""

from typing import ClassVar

from django.conf import settings
from django.db import migrations, models
from django.db.migrations.operations.base import Operation


class Migration(migrations.Migration):

    dependencies: ClassVar[list[tuple[str, str]]] = [
        ('commentail', '0013_sitecommentsettings_email_enabled'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations: ClassVar[list[Operation]] = [
        migrations.AlterField(
            model_name='rateevent',
            name='created_at',
            field=models.DateTimeField(auto_now_add=True, db_index=True),
        ),
        migrations.AddIndex(
            model_name='comment',
            index=models.Index(fields=['status', 'published_at', 'id'], name='commentail_publication_order'),
        ),
        migrations.AddIndex(
            model_name='comment',
            index=models.Index(fields=['root', 'status', 'published_at', 'id'], name='commentail_reply_order'),
        ),
        migrations.AddIndex(
            model_name='comment',
            index=models.Index(condition=models.Q(('root__isnull', True)), fields=['discussion', 'published_at', 'id'], name='commentail_root_order'),
        ),
        migrations.AddIndex(
            model_name='captchachallenge',
            index=models.Index(condition=models.Q(used=False), fields=['site', 'session_digest'], name='commentail_active_captcha'),
        ),
    ]
