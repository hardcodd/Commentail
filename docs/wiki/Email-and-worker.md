# Email delivery, notifications and the worker

Commentail supports any backend implementing Django's email backend contract
through `EMAIL_BACKEND`. It also provides a public Python entry point for the
host task queue; choose one scheduler for the background processing described below.

## Choose a Django email backend

Configure `EMAIL_BACKEND`, `DEFAULT_FROM_EMAIL` and the settings required by your
backend. Non-SMTP backends do not need `EMAIL_HOST`, SMTP credentials or SMTP
constructor options. Commentail does not contact or instantiate the transport
when deciding whether to offer a guest form; availability is a configuration
check, not a delivery check.

Console, file, in-memory and dummy backends follow their normal Django behavior:
they can enable guest forms in development but do not deliver to a real inbox.
Use a real delivery backend in production. A backend must report one accepted
message from `send_messages()` for the job to be marked sent. If a backend merely
enqueues delivery elsewhere, that acceptance is the end of Commentail's tracking;
later provider failures must be monitored in the host system.

Configure a finite network timeout in a non-SMTP backend's own settings, shorter
than `MAIL_LEASE_SECONDS` (default 300 seconds). Commentail does not impose
SMTP-specific timeout arguments on it. For Django SMTP and its subclasses,
Commentail caps the timeout at half the lease, up to 30 seconds, while retaining
a shorter configured `EMAIL_TIMEOUT`.

### API delivery

Install your chosen provider's Django email backend in the host project, or
implement Django's backend contract there. Set `EMAIL_BACKEND` to that backend's
documented Python class path and configure its API key, sender and timeout using
its own settings. A provider name, API URL or API key is not an `EMAIL_BACKEND` value.
Commentail does not bundle a provider SDK or a Resend-specific backend.

Keep credentials in the host environment or secret store, not in `COMMENTAIL`.
Verify the provider's sender/domain and recipient restrictions before a real test.
An importable backend enables the guest form; it does not validate those credentials
or prove the provider can deliver. The same outbox/schedule is used for SMTP and API mail.

### Local testing without a provider

In a test project's settings, use:

```python
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
DEFAULT_FROM_EMAIL = "comments@example.invalid"
```

The background process prints mail to its own terminal/log instead of an inbox.
Open the printed action link to continue the guest flow. Keep those protected
links private. This checks application behavior, not external delivery.

## SMTP example

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

## Email presentation

All five notification types include minimal HTML and a plain-text alternative.
The header uses the Wagtail Site name; the main action is a link styled as a button,
with a copyable URL and descriptive secondary links. Confirmation still requires
an explicit action on the confirmation page; unsubscribe still requires an
explicit action on its page. Editing ends as soon as a direct reply is submitted, even before moderation.
Revision approval/rejection is worded separately from comment approval/rejection.
Approval of changes does not imply that a hidden comment becomes visible.
No comment text, external images, fonts or tracking assets are added.

Existing host overrides take
precedence over package templates, including the shared HTML shell. Review both
MIME alternatives together; see [Templates](Templates.md).

## Use the host task queue

Call this public synchronous function from a periodic task in your existing queue:

```python
from commentail.background import process_pending

result = process_pending(mail_limit=100)
# {"sent": 3, "removed": 1}
```

`mail_limit` must be a positive integer (default 100); invalid values raise
`ValueError` before database access. It limits mail claims per
pass, including cancelled/deferred jobs, not the amount of cleanup. The returned
JSON-compatible dictionary contains `sent` (messages accepted by the backend) and
`removed` (expired unconfirmed comments erased, excluding related records).
The same pass expires CAPTCHA proofs, guest grants, form tickets and old rate
records. Internal outbox functions and models are not the task integration API.

Run after Django initialization, against the site's database and settings, outside
`transaction.atomic()` and with autocommit enabled. A caller transaction raises
`TransactionManagementError` before cleanup or sending. Unexpected errors propagate
to your task monitor; completed work is not rolled back as one batch. Configure
transport timeouts below the lease and give the host task enough time for the batch.

For a project already using Celery, an installed host app's `tasks.py` can contain:

```python
from celery import shared_task
from commentail.background import process_pending


@shared_task(name="myapp.process_commentail")
def process_commentail_task():
    return process_pending(mail_limit=100)
```

With the usual Celery `namespace="CELERY"` configuration, add an entry to the
host's existing `CELERY_BEAT_SCHEDULE` in Django settings:

```python
CELERY_BEAT_SCHEDULE = {
    # Preserve the project's other periodic tasks here.
    "commentail-every-minute": {
        "task": "myapp.process_commentail",
        "schedule": 60.0,
    },
}
```

Use your real host app/task names and keep its workers and scheduler running.
The wrapper and periodic settings follow the [Celery 5.6 Django integration](https://docs.celeryq.dev/en/v5.6.0/django/first-steps-with-django.html)
and [periodic task documentation](https://docs.celeryq.dev/en/v5.6.0/userguide/periodic-tasks.html).
Celery is optional and is not installed or configured by Commentail. Other queues
can wrap the same synchronous function; Commentail does not register queue tasks
or enqueue a broker message from an HTTP request.

Schedule once per minute. Use either the host task or the command schedule below;
a separate Commentail cron job is unnecessary with a functioning host schedule.
The DB outbox remains authoritative for retry timing, original link deadlines and
access checks. Do not replace its retries with per-email broker retries. Duplicate
task execution respects active claims and sent status; an expired lease after an
uncertain send can still cause duplicate mail. Monitor task failures and queue age,
and size the batch/frequency for your backlog. Delayed queue execution delays
mail; it never extends a protected link's lifetime.

## Schedule the command once per minute

The `python manage.py process_commentail` command calls the same public function.
Run it once per minute if you are not using the host task schedule. It processes the
DB outbox and expires unconfirmed comments without Redis/Celery. The 24-hour
confirmation deadline starts at acceptance. Retries/owner resends reuse the
original job/token without extending it. Guest publication creates a separate
editing-link email. Editing lasts 15 minutes from publication and ends permanently
when a direct reply is accepted, even before that reply is moderated.

Delivery runs outside state-transition transactions. Temporary/uncertain failures
retry after 1, 5 and 15 minutes; permanent SMTP refusals require explicit retry.
Other backend exceptions and results that do not report one accepted message
use the same bounded retries, then become failed jobs. Only the exception class
is saved, without provider response text or credentials. Rendering/domain errors
remain failures requiring correction; they are not treated as provider errors.
Leases prevent concurrent claims, but uncertain results can cause duplicate mail;
a stable Message-ID does not guarantee exactly-once delivery. Hidden discussions
defer mail. Lost access, disabled subscriptions and expired links cancel it.
Reply emails contain author names and links, never comment text.

The submitting guest browser shows a private confirmation-mail status: queued,
sending, sent, automatic retry, failed or unavailable, plus the original deadline.
Sent means the configured mail backend accepted the message, not inbox delivery.
Backend diagnostics, email addresses and tokens are never included in that status.
Resend is offered only before expiry while no worker is sending the message.
Status updates appear on reload; normal resend forms also work without JavaScript.

```cron
* * * * * cd /srv/site && /srv/site/.venv/bin/python manage.py process_commentail >> /var/log/site/commentail.log 2>&1
```

Adapt paths, environment, settings module and log rotation. Starting the web server
alone does not send mail or clear expired proofs. Use the same database as the site.

## Verify the complete delivery flow

1. Use a test discussion and an email address you control. For a real provider,
   use its authorized sender and a recipient permitted by the account's current setup.
2. In a fresh browser session, submit a guest comment. It should show a private
   awaiting-confirmation status and create a queued message in **Comments → Email delivery**.
3. Let the configured scheduler run. With the command approach, you can run
   `python manage.py process_commentail` once. With a host queue, run its task
   through the real broker/worker and inspect task and outbox status.
4. Check the received message, sender and action URL, including the host scheme,
   domain and Commentail URL prefix. Inspect spam and provider delivery events if needed.
5. Follow the link and press Confirm. Approve the comment if moderation requires
   it, then check the editing-link email and an eligible edit. Submit and approve
   a direct reply, then test its per-comment unsubscribe.

A direct Django `send_mail()` test checks the backend only. It does not test
Commentail's outbox, task registration, scheduler or guest-confirmation flow.
Backend acceptance, provider delivery and inbox placement are separate results.

## Subscription and mail switches

When Site mail and a configured email backend are enabled, public submissions
automatically subscribe an author who has an email. There is no checkbox; a brief notice appears after
acceptance. Only direct published replies generate reply notifications. Every reply
mail includes per-comment unsubscribe. Old comments and prior opt-outs are never
resubscribed retroactively.

The Site **Send emails** switch defaults on and cannot be overridden on a Page.
Disabling it cancels queued mail; reenabling does not replay cancelled jobs.
Publication/rejection emails are separate switches, off by default. Publication
notices are sent only when a pending comment or author revision is approved by a
moderator. Immediate publication sends no publication notice to its author,
whether registered or a guest. Reply notifications and guest confirmation/editing
links still follow their own rules. Rejection emails also apply to revision
decisions. Guest editing-link email is separate. Deleting an account
cancels its mail/subscriptions and removes stored comment email.

## Operate the queue

Use Comments → Email delivery, filter by Site/status, fix the underlying problem,
then retry eligible failures with moderation permission. Original expiry and access
still apply. Sent means backend acceptance, not inbox delivery. See
[Templates](Templates.md) for overrides and [Troubleshooting](Troubleshooting.md).

After restoring an older database backup, keep the worker paused until the queue
has been reviewed. Jobs pending in that snapshot may already have been delivered
later; restoring them can send duplicates with the original Message-ID. See
[upgrade and restoration](Installation.md#upgrading-and-restoring).

---

[← Replies and editing](Replies-and-editing.md) · [Documentation home](Home.md) · [Styling →](Styling.md)
