"""Erase account metadata and cascade registered target deletion through the ORM."""

from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser
from django.db.models.signals import pre_delete
from django.dispatch import receiver

from .models import Comment
from .objects import clear_object_discussions


@receiver(pre_delete, sender=settings.AUTH_USER_MODEL)
def anonymize_account(
    sender: type[AbstractBaseUser], instance: AbstractBaseUser, **kwargs: object
) -> None:
    # No historical account name/email remains in the public comment record.
    """Erase historical account metadata and disable its queued mail/subscriptions."""
    Comment.objects.filter(user_id=instance.pk).update(
        email="", guest_name="", email_confirmed_at=None, account_deleted=True
    )

    from .models import MailJob, ReplySubscription

    MailJob.objects.filter(
        recipient__user_id=instance.pk, status__in=["pending", "sending", "failed"]
    ).update(status="cancelled")
    ReplySubscription.objects.filter(comment__user_id=instance.pk).update(enabled=False)


pre_delete.connect(
    clear_object_discussions, dispatch_uid="commentail.object_cleanup", weak=False
)
