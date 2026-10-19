# SMTP, notifications and the worker

## Configure Django SMTP

```python
import os

EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = os.environ["EMAIL_HOST"]
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_USE_SSL = False
EMAIL_HOST_USER = os.environ["EMAIL_HOST_USER"]
EMAIL_HOST_PASSWORD = os.environ["EMAIL_HOST_PASSWORD"]
DEFAULT_FROM_EMAIL = "Comments <comments@example.org>"
EMAIL_TIMEOUT = 20
```

Use your provider's actual settings and authorized sender. Implicit TLS normally
uses port 465 with SSL=True and TLS=False; never enable both. Keep credentials
outside source. Correct configuration is not proof of inbox delivery: test a real
message. Configure correct Wagtail Site host/port and HTTPS/proxy settings for links.
Email action and status links use the named `commentail:action` route, including
the prefix where your project includes `commentail.urls`.

Subjects and bodies use the recipient's saved comment language, independently
of the worker's active language. Reply notifications use the original recipient's
language. User-entered rejection reasons remain unchanged. See
[available languages](Configuration.md#languages).

## Schedule once per minute

Run `python manage.py process_commentail` once per minute. It processes the
DB outbox and expires unconfirmed comments without Redis/Celery. The 24-hour
confirmation deadline starts at acceptance. Retries/owner resends reuse the
original job/token without extending it. Guest publication creates a separate
editing-link email. Editing lasts 15 minutes from publication and ends permanently
when a direct reply is accepted, even before that reply is moderated.

SMTP runs outside state-transition transactions. Temporary/uncertain failures
retry after 1, 5 and 15 minutes; permanent refusals require explicit retry.
Leases prevent concurrent claims, but uncertain results can cause duplicate mail;
a stable Message-ID does not guarantee exactly-once delivery. Hidden discussions
defer mail. Lost access, disabled subscriptions and expired links cancel it.
Reply emails contain author names and links, never comment text.

The submitting guest browser shows a private confirmation-mail status: queued,
sending, sent, automatic retry, failed or unavailable, plus the original deadline.
Sent means the configured mail backend accepted the message, not inbox delivery.
SMTP diagnostics, email addresses and tokens are never included in that status.
Resend is offered only before expiry while no worker is sending the message.
Status updates appear on reload; normal resend forms also work without JavaScript.

```cron
* * * * * cd /srv/site && /srv/site/.venv/bin/python manage.py process_commentail >> /var/log/site/commentail.log 2>&1
```

Adapt paths, environment, settings module and log rotation. Starting the web server
alone does not send mail or clear expired proofs. Use the same database as the site.

## Subscription and mail switches

When Site mail and SMTP are enabled, public submissions automatically subscribe
an author who has an email. There is no checkbox; a brief notice appears after
acceptance. Only direct published replies generate reply notifications. Every reply
mail includes per-comment unsubscribe. Old comments and prior opt-outs are never
resubscribed retroactively.

The Site **Send emails** switch defaults on and cannot be overridden on a Page.
Disabling it cancels queued mail; reenabling does not replay cancelled jobs.
Publication/rejection emails are separate switches, off by default, also applying
to revision decisions. Guest editing-link email is separate. Deleting an account
cancels its mail/subscriptions and removes stored comment email.

## Operate the queue

Use Comments → Email delivery, filter by Site/status, fix the underlying problem,
then retry eligible failures with moderation permission. Original expiry and access
still apply. Sent means SMTP acceptance, not inbox delivery. See
[Templates](Templates.md) for overrides and [Troubleshooting](Troubleshooting.md).

After restoring an older database backup, keep the worker paused until the queue
has been reviewed. Jobs pending in that snapshot may already have been delivered
later; restoring them can send duplicates with the original Message-ID. See
[upgrade and restoration](Installation.md#upgrading-and-restoring).

---

[← Replies and editing](Replies-and-editing.md) · [Documentation home](Home.md) · [Styling →](Styling.md)
