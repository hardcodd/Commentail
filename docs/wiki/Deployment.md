# Deployment and operations

## Integration checklist

- Install a supported version in a test environment; back up your database.
- Run migrations, system checks and collectstatic; serve the static assets.
- Check Wagtail Site host/port, HTTPS scheme, ALLOWED_HOSTS, cookies and proxy settings.
- Configure SMTP through secrets/environment and verify real delivery.
- Schedule process_commentail once per minute against the site's database.
- Assign moderator rights per Site; begin with Review all.
- Keep personalized widget/action responses out of shared caches.

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

## Monitor

Use Comments and Email delivery for status; monitor worker exit failures, queue age,
SMTP acceptance and database health in your own operations system. Leases prevent
parallel claims, but uncertain SMTP delivery can produce duplicates. Redact protected
URLs and rotate logs. Do not suppress host security checks to pass deployment.

---

[← Security and privacy](Security-and-privacy.md) · [Documentation home](Home.md) · [Troubleshooting →](Troubleshooting.md)
