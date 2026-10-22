# Deployment and operations

## Integration checklist

- Install a supported version in a test environment; back up your database.
- Run migrations, system checks and collectstatic; serve the static assets.
- Check Wagtail Site host/port, HTTPS scheme, ALLOWED_HOSTS, cookies and proxy settings.
- Enforce request-body, request-rate and connection limits at the web server/proxy;
  application quotas do not replace protection against distributed traffic.
- Configure [email delivery](Email-and-worker.md) through secrets/environment and
  verify real delivery. SMTP and other Django backends are supported.
  Configure their timeout below the mail lease.
- Schedule background processing once per minute against the site's database:
  `process_commentail`, or the host queue calling
  [`commentail.background.process_pending()`](Email-and-worker.md#use-the-host-task-queue).
- Assign moderator rights per Site; begin with Review all.
- Keep personalized widget/action responses out of shared caches.
- Check [database/query costs and load-test guidance](Performance.md) against your
  expected traffic; account for index-building time when upgrading large tables.

## Host acceptance

Test a registered comment, approval, direct reply and eligible edit. In another
browser test guest proof, moderation, publication mail and unsubscribe. Check target
access with another visitor, settings inheritance, hidden/read-only modes, custom
handlers/templates, actual light/dark themes, narrow layouts, keyboard and no-JS forms.
Monitor the mail queue and scheduler; exercise a recoverable mail error and cleanup.

## Backup and upgrades

Back up database, host configuration, uploaded profile images and template overrides
using your site's policy. Test upgrades first and compare overrides with the new
bundled templates. Preserve the old wheel and database backup for recovery; a package
rollback alone does not reverse schema/data changes. Do not widen dependency bounds
and assume compatibility. The development example is not a production template.

### Private fingerprint migration `0018`

For the security update after 1.3.0, rehearse migration on a restored database.
Stop web writers and background workers before migrating; do not run old and new
application versions against the database together. Retain the same `SECRET_KEY`
through this migration. Back up the database, key, configuration and old package
together before starting.

Run `migrate`, `check` and `collectstatic` with the new package before restarting
processes. `0018` transforms existing quota/submission fingerprints in bounded
batches inside one transaction; large ledgers still require time, locks and
transaction storage. It preserves live random links, forms, browser proofs and
existing content fingerprints. Test an existing form retry, guest/account
submissions, CAPTCHA refusal, form throttling, draft recovery and mail access.
Review form overrides against the new issuance-error/disabled-submit behavior.

The transformation cannot be reversed by `migrate` or reinstalling the old wheel.
Recovery requires restoring the matching pre-upgrade database and package under
the original key, with writers stopped. Backups need their own access/retention
policy; this migration does not rewrite old exports or backups.

## Monitor

Use Comments and Email delivery for status; monitor worker exit failures, queue age,
backend acceptance and database health in your own operations system. Leases prevent
parallel claims, but uncertain delivery can produce duplicates. Redact protected
URLs and rotate logs. Do not suppress host security checks to pass deployment.

---

[← Security and privacy](Security-and-privacy.md) · [Documentation home](Home.md) · [Troubleshooting →](Troubleshooting.md)
