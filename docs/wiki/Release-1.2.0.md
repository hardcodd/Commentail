# Commentail 1.2.0

**Stable · 22 October 2026**

Install with `python -m pip install commentail==1.2.0`.

## Changes

- Use the configured Django `EMAIL_BACKEND` for guest verification and queued
  mail, including API-based backends. Non-SMTP backends no longer need SMTP
  settings. Configure the backend and its credentials in the host project.
- Schedule `commentail.background.process_pending(mail_limit=100)` through the
  project's existing task queue. The management command remains supported;
  choose one schedule. The database outbox still controls claims, retries,
  access checks and original link deadlines.
- Put reply cancellation beside Send comment as a quiet text action with a
  button surface on hover/focus. Compact the guest form, shorten the CAPTCHA
  field, place refresh beside it and clarify the email-confirmation hint.
  The submit button is emphasized using the host's text color.
- Reject oversized navigation/filter IDs, null bytes in comment text/names and
  guest email addresses longer than the stored field. Redact capability tokens
  from Django logs when the query parameter name is percent-encoded.
- Verify Wagtail 8.0.1 in the supported Wagtail 8 stacks. Update the test pins
  for certifi and Pillow to versions addressing the previous known advisories;
  these pins are not a production dependency lockfile for integrating sites.

## Upgrade from 1.1.0

1. Rehearse on a restored test database. Keep mail local; back up the database,
   host settings, templates, media, `SECRET_KEY` and exact dependency versions.
2. Install `commentail==1.2.0` or a verified release artifact in the test
   environment. No new Commentail migration is added over 1.1.0; framework
   upgrades may have their own migrations. Run `migrate` and `check` as usual.
3. Run `collectstatic --noinput`, refresh cached assets and restart application
   and background processes through your normal deployment procedure.
4. Compare overrides of `commentail/form.html` and `commentail/captcha.html`
   with the installed templates. Preserve form fields, CSRF, hidden keys and
   JavaScript hooks. Existing overrides keep precedence and need corresponding
   markup/CSS changes to adopt the new layout. Custom button fills need a
   contrasting text color; no site-specific CSS variables are required by default.
5. Existing SMTP plus the once-per-minute command needs no configuration change.
   For an API backend, follow its settings/timeout requirements. For a host queue,
   schedule `process_pending()` once per minute outside a database transaction
   and remove the separate command schedule. See [email and scheduling](Email-and-worker.md).
6. Check signed-in and guest submissions, confirmation, moderation, replies,
   eligible edits, unsubscribe and queued mail. Test keyboard/no-JS forms and
   the actual light/dark themes. Monitor background failures and queue age.

Existing comments, settings, subscriptions, issued links and queued jobs are
retained. Protected-link deadlines are not extended. Backend acceptance does not
prove inbox delivery; an uncertain send can still be retried and duplicated.
Host proxy logs and error reporting must redact protected links independently.
See [installation and restoration](Installation.md#upgrading-and-restoring).

For an earlier starting version, also follow the intervening
[1.1.0](Release-1.1.0.md), [1.0.0](Release-1.0.0.md), [0.2.0](Release-0.2.0.md) and [0.1.1](Release-0.1.1.md)
notes as applicable.

## Verification boundaries

The updated development runtime passed the local 30-combination matrix:
395 tests per combination, with one SQLite-only plan test skipped on each
PostgreSQL run. JavaScript, lint, translations, migration drift, source/wheel
archives and the runnable example passed. Real API mail and Redis/Celery
integration were checked separately; responsive/theme checks covered the new forms.
These are local results, not published-package or exact-commit hosted CI results.
Each integrating site must verify its own access rules, overrides and delivery.
