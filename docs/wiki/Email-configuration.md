# Separate email delivery for Commentail

English · [Русский](Email-configuration-ru.md)

**Available since 1.4.0.** Earlier versions use the
project's shared Django email configuration. With 1.4.0, Commentail can use a
different backend, connection settings and sender while ordinary Django mail
continues using the project's existing configuration.

## Configuration reference

Add `COMMENTAIL_EMAIL` to the host project's Django settings. It is a separate,
project-wide dictionary, outside `COMMENTAIL`; it has no hostname sections or
Wagtail admin fields. All Commentail email types use it.

| Key | Default | Meaning |
| --- | --- | --- |
| `BACKEND` | `None` | Import path to a Django email backend class. `None` or omission uses the project's `EMAIL_BACKEND`. |
| `OPTIONS` | `{}` | Constructor keyword arguments for an explicit `BACKEND`. Nonempty options require an explicit backend path. |
| `FROM_EMAIL` | `None` | Nonempty sender string, optionally with a display name. `None` or omission uses `DEFAULT_FROM_EMAIL`. |

Omitting `COMMENTAIL_EMAIL`, or setting it to `{}`, preserves shared delivery.
A sender-only override is also valid:

```python
COMMENTAIL_EMAIL = {"FROM_EMAIL": "Comments <comments@example.org>"}
```

Only constructor options supported by the chosen backend belong in `OPTIONS`.
Use lowercase names such as SMTP's `host`, not Django setting names such as
`EMAIL_HOST`. The `backend` and `fail_silently` option names are reserved:
Commentail always uses `fail_silently=False`. It never switches to the shared backend after an
explicit backend fails.

`python manage.py check` validates dictionary structure and backend imports
without constructing a transport or making a network request. Passing checks
does not verify provider credentials, sender authorization or delivery.

## Separate SMTP connection

Merge this into the project's `settings.py`; preserve its ordinary `EMAIL_*`
settings. Supply the environment variables to both the web application and its
background processes using your existing service or secret configuration.

```python
import os

COMMENTAIL_EMAIL = {
    "BACKEND": "django.core.mail.backends.smtp.EmailBackend",
    "OPTIONS": {
        "host": os.environ["COMMENTAIL_SMTP_HOST"],
        "port": 587,
        "username": os.environ["COMMENTAIL_SMTP_USERNAME"],
        "password": os.environ["COMMENTAIL_SMTP_PASSWORD"],
        "use_tls": True,
        "use_ssl": False,
        "timeout": 20,
    },
    "FROM_EMAIL": os.environ["COMMENTAIL_FROM_EMAIL"],
}
```

Set `COMMENTAIL_FROM_EMAIL` to a sender authorized by the provider, for example
`Comments <comments@example.org>`. Use its real SMTP host and credentials.
For implicit TLS, use the provider's port (normally 465), `use_ssl=True` and
`use_tls=False`. Never enable both TLS modes.

Omitted SMTP options retain Django's corresponding `EMAIL_*` defaults: an
explicit backend alone does not isolate credentials. Specify all connection
fields needed for a separate account, including credentials and TLS modes.
For guest forms, SMTP requires an explicit nonempty `host` option or an explicitly
configured nonempty `EMAIL_HOST`. A `None` host option inherits `EMAIL_HOST`.
An empty or whitespace-only host disables guest forms and refuses queued SMTP
construction; that failure follows the existing bounded retry policy.
Commentail caps SMTP timeouts at half the job lease, up to 30 seconds, retaining
shorter values; other backends manage their own finite timeouts.

## HTTP API example: Resend through Anymail

This optional integration belongs to the host project. Commentail installs no
provider SDK. In a test environment, install the version used by this example:

```sh
python -m pip install django-anymail==15.2
```

Append `"anymail"` to the existing `INSTALLED_APPS`. Preserve the site's shared
SMTP `EMAIL_BACKEND` and `EMAIL_*` settings, and add:

```python
import os

COMMENTAIL_EMAIL = {
    "BACKEND": "anymail.backends.resend.EmailBackend",
    "OPTIONS": {
        "api_key": os.environ["COMMENTAIL_RESEND_API_KEY"],
        "requests_timeout": 20,
    },
    "FROM_EMAIL": os.environ["COMMENTAIL_FROM_EMAIL"],
}
```

Use a Resend sending key, an authorized sender/domain and a recipient permitted
by the account. This uses Anymail's
[Resend backend](https://anymail.dev/en/v15.2/esps/resend/) and documented
[per-instance options](https://anymail.dev/en/v15.2/installation/#anymail-settings-reference).
For other backends, use their documented constructor arguments or own Django
settings; SMTP option names are not universal.

Keep secrets in environment variables or a secret store. A `.env` file is not
loaded automatically by Django or inherited automatically by a service worker.
Do not print configuration dictionaries or enable raw provider request logging
when checking credentials.

## Apply and verify

For a direct transport probe, explicitly select a test recipient you control:

```sh
python manage.py test_commentail_email --to recipient@example.org
```

This sends one plain-text test email with the resolved Commentail backend and
sender. It creates no comment, token, subscription or outbox job and does not
process pending mail. It runs directly, even when Site email is disabled, so it
checks transport configuration rather than a Site's delivery policy or worker.
SMTP timeout is capped at 30 seconds; other backends use their own timeout
options. Errors show only the exception class, never provider response text or
credentials. A nonzero exit means the probe failed; do not assume a retry cannot
send a duplicate. Backend acceptance does not confirm inbox delivery (local,
console and dummy backends may also report acceptance).

1. Install `commentail==1.4.0` in your site environment. Run `python manage.py check` with the intended settings.
2. Restart the web application and the background workers after changing
   configuration. Keep their settings, environment and database aligned.
3. Test ordinary site mail through the site's normal feature. It should still
   use the shared backend and sender.
4. Submit a guest comment and run the existing worker or
   `python manage.py process_commentail`. Check **Comments → Email delivery**,
   the provider event and the received sender/link; complete email confirmation.
5. Follow the [full notification flow](Email-and-worker.md#verify-the-complete-delivery-flow)
   to check editing, replies and unsubscribe.

The existing queue, scheduler, retries, access checks and link deadlines remain
in use. Pending jobs use the active backend and sender when processed, including
jobs created before a configuration change. A failed job does not automatically
become eligible again when credentials change: fix the cause and use the
existing retry action where allowed.

Provider failures and invalid active email configuration use the existing retry
budget and release the job lease; queue diagnostics retain the
exception class, not private response text. A sent job means backend acceptance,
not delivery to an inbox. Mocked or local development-backend checks cannot prove
real provider delivery. See [troubleshooting](Troubleshooting.md).

[Configuration](Configuration.md) · [Email and worker](Email-and-worker.md)
