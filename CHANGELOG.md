# Changelog

Each release records changes relative to the previous version. Upgrade notes
describe changes that an existing installation needs to review.

## Unreleased

### Added

- German (`de`), French (`fr`), Spanish (`es`) and Brazilian Portuguese (`pt-br`)
  translations for public forms, validation/action messages, moderation/settings,
  delivery screens and all five notification email types, including revision decisions.
- Source-coverage and compiled-catalog checks for every shipped locale, plus
  regression checks for recipient-language mail delivery and English fallback.

### Fixed

- Generated author labels in reply emails use the recipient's saved language,
  including the generic account name, instead of the mail worker's language.

### Upgrade notes

- These locales are in the source tree and are not included in published 0.1.1.
- Enable the desired language through the host site's Django language settings;
  use `pt-br` for Brazilian Portuguese. Commentail's gettext directory is `pt_BR`.
- Documentation remains in English and Russian. No new database migrations.

## [0.1.1] — 2026-10-19 · Beta

Changes from **0.1.0 → 0.1.1**.

### Added

- Wagtail 8.0 support with Django 5.2, 6.0 or 6.1, and Django 6.0 support on
  Wagtail 7.4.3+. The five framework pairs cover Python 3.12–3.14 with file
  SQLite and PostgreSQL 16 (30 combinations).
- Regression coverage for capability access, extension/presentation contracts,
  lifecycle transactions, concurrency and mail-worker recovery.
- A public roadmap, including expansion of supported UI and email languages/locales.

### Changed

- New guest names allow **40 Unicode graphemes**, down from 80, after trimming.
  Server validation and browser guidance reject overlong input without truncation.
  Existing stored names and registered-account names are preserved.
- PostgreSQL installation guidance explicitly includes `django.contrib.postgres`
  for Django 6.x checks.

### Fixed

- Email action and status links now follow the configured Commentail URL prefix,
  including nested paths, instead of assuming `/commentail/`.
- The guest-name label uses its own translation context, preventing collisions
  with host-site translations for other uses of "Name".

### Upgrade notes

- No new Commentail database migrations; framework upgrades may have their own.
- Review overridden guest forms for the 40-grapheme limit and recollect static files.
- Previously delivered emails are not rewritten. Pending mail uses the installed
  version's URL generation; existing SMTP retry/duplicate-delivery limits remain.
- UI and email languages remain English and Russian. Additional locales are planned.

See [0.1.1 release notes](docs/releases/0.1.1.md) and
[installation/restoration](docs/wiki/Installation.md).

## [0.1.0] — 2026-10-17 · Beta

Initial release for Wagtail 7.4.3+ within 7.4, Django 5.2 and Python 3.12–3.14.

- Template-based Page integration and adapters for ordinary Django models.
- Site/Page configuration, moderation queue, group permissions and CSV rules.
- Verified guests, replaceable CAPTCHA and Site-scoped rate limits.
- Threaded replies, inline author revisions and protected guest actions.
- Database email outbox, direct-reply notifications and unsubscribe.
- Schema.org Comment microdata and JSON-LD, with per-site output selection.
- Theme inheritance, template overrides, Python hooks and English/Russian UI.

See [0.1.0 release notes](docs/releases/0.1.0.md).

[0.1.1]: https://github.com/hardcodd/Commentail/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/hardcodd/Commentail/releases/tag/v0.1.0
