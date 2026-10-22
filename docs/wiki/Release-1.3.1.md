# Commentail 1.3.1 — security update

**Released 23 October 2026.** Review the migration requirements before upgrading.

## Changes

- Key predictable quota identities and submission actor/payload fingerprints with
  purpose-scoped HMAC. Site/event and discussion scopes separate these values.
  Existing quotas and accepted retries survive the data migration. Later key
  rotation supports Django's `SECRET_KEY_FALLBACKS` for these records.
- Require Page discussions to stay inside their saved Site's root tree. Direct
  endpoints, protected links and queued mail deny foreign/moved targets.
- Bound new form/recovery tickets for guests and registered users, including
  reading navigation: 120 per IP/Site/minute and 1200 per hour by default.
  Refusal preserves reading and entered text, creates no CAPTCHA, and leaves
  existing valid tickets usable. Configure the limits for shared networks.
- Identify object-adapter configuration errors separately: model resolution,
  supported primary key, duplicates, import/class and missing callable methods.
  Arbitrary adapter exception payloads remain private.
- Delete expired CAPTCHA, guest grants, form tickets and rate events in batches
  of at most 500, each in a separate transaction. Active records remain intact;
  a later failure does not roll back previously committed cleanup batches.

## Upgrade from 1.3.0

1. Rehearse on a restored database. Back up the database, `SECRET_KEY`, settings,
   overrides and exact old package/dependency versions together.
2. Stop web/background writers. Install the approved new package, keep the same
   key, run `migrate`, `check` and `collectstatic`, then restart processes. Do not
   mix old/new writers. Migration `0018_private_fingerprints` is a data migration
   in one transaction; large ledgers need maintenance time and transaction space.
3. The transformation is irreversible. Downgrade requires restoring the matching
   pre-upgrade database and package with writers stopped. Reinstalling 1.3.0 or
   reversing migrations alone cannot restore compatible fingerprints. Old
   backups/exports retain their earlier hashes and need separate protection.
4. Random capability/form hashes, guest grants and already-keyed duplicate-text
   signals stay unchanged. Verify an open form and accepted retry, guest/account
   submissions, CAPTCHA errors, draft recovery, replies, protected links and mail.
5. Review custom form templates for the issuance error and disabled submit state.
   Set `FORM_IP_LIMIT_PER_MINUTE` / `FORM_IP_LIMIT_PER_HOUR` for real traffic and
   shared networks; configure actual trusted proxies. Schedule existing cleanup.
   At the limit the response keeps entered values, but cannot store another
   recovery ticket; Retry check preserves the fields and restores issuance after
   the window expires. Keep the displayed draft before leaving the page.

No dependency or database-schema changes are introduced. See [deployment and
recovery](Deployment.md#private-fingerprint-migration-0018) and
[security/privacy contracts](Security-and-privacy.md).

## Verification boundaries

Regression coverage exercises each diagnostic cause, fingerprint upgrade/key
rotation, foreign Page access and mail, form issuance/refusal/recovery and
concurrent quotas. Before the batched-cleanup follow-up, the candidate wheel
passed all 30 local combinations of
Python 3.12–3.14, the five supported Django/Wagtail pairs, and file SQLite /
PostgreSQL 18. Each combination ran 490 tests; PostgreSQL skipped only the
SQLite-specific query-plan test. All 49 JavaScript tests, five translation
catalogs, CI-pinned lint, migration checks, archive/RECORD and strict metadata
checks passed. A synthetic legacy database upgraded through the real migration;
reverse execution was rejected and its matching backup verified. Firefox
retained fields through refusal and restored the form after the window expired.

The subsequent batched-cleanup change adds five regressions covering multiple
batches and commits, active records, failure recovery, expiry boundaries and
expiry rechecks. The full 495-test suite passed on both file SQLite and
PostgreSQL 18.6 with Python 3.12 / Django 5.2 / Wagtail 7.4 and Python 3.14 /
Django 6.1 / Wagtail 8.0. PostgreSQL skipped only the SQLite-specific query-plan
test; all 12 background tests and migration checks also passed in both stacks.
The 30-way matrix above predates this follow-up and has not been rerun for it.

Publication requires successful hosted CI for the exact publishing commit
(including PostgreSQL 16). Deployment remains a separate operation.
This review does not prove absence of all
vulnerabilities or measure deployed capacity. HTTPS, host CSRF/session settings,
proxy request/connection limits, backups, logs and timely dependency updates
remain deployment responsibilities. No external service keys or real inboxes
were used for this update.
