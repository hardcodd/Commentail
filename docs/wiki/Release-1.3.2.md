# Commentail 1.3.2 — translated Site roots

**Released 23 October 2026.** This patch fixes a regression introduced in 1.3.1.

## Changes

With `WAGTAIL_I18N_ENABLED=True`, Wagtail can serve a Site's translated
homepages from sibling page trees. The 1.3.1 Site-boundary check only accepted
the configured root tree, making valid translated discussions unavailable.

Commentail now also accepts trees rooted at translations of the Site's
homepage. This applies consistently to the widget, forms and submissions,
protected links, queued email and recent comments. The actual page must still
be live and pass its own inherited view restrictions. Unrelated trees, moved
pages outside the allowed trees and capabilities for another Site remain denied.
With content internationalization disabled, only the configured root tree is
accepted.

## Upgrade from 1.3.1

1. Back up the site using your normal procedure and install
   `python -m pip install commentail==1.3.2` in its environment.
2. Run `migrate`, `check` and `collectstatic --noinput`, then restart application
   and background processes. There is no new Commentail migration, dependency
   change or template change over 1.3.1.
3. Check existing discussions in every language, a new submission, protected
   guest links and queued mail. Verify that restricted pages remain private.
   Existing discussions do not need to be recreated or reassigned to another Site.

This fix does not automatically requeue email jobs already cancelled by 1.3.1.
Review their state separately before deciding whether a replacement is needed.

For installations behind nginx, explicitly configure the actual
[`TRUSTED_PROXIES`](Deployment.md#client-ip-behind-nginx) and verify
forwarded-header handling so visitors do not share the proxy's IP quotas.

## Upgrade from 1.3.0 or earlier

Also follow the [1.3.1 upgrade procedure](Release-1.3.1.md). Its irreversible fingerprint
migration `0018` still requires stopped writers, the same key and a matching
database/key/package backup. This patch does not remove that requirement.

## Verification

Thirteen new regressions cover translated roots and descendants, rendered host
widgets, registered submissions, guest links/mail, inherited restrictions,
disabled internationalization, unpublished pages, moved targets and Site isolation.
The 508-test Python suite passed locally on Wagtail 7.4 / Django 5.2 and
Wagtail 8.0 / Django 6.1 using SQLite; the eight concurrency tests ran separately
against file databases. Lint, formatting and migration checks passed.
Publication is gated on successful hosted CI for the exact publishing commit,
including the supported framework/Python matrix and PostgreSQL 16.

Deployment and acceptance on an existing production site are separate checks.
