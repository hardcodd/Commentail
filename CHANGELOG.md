# Changelog

Each release records changes relative to the previous version. Upgrade notes
describe changes that an existing installation needs to review.

## [1.4.0] — Unreleased · Independent email and early rule rejection

- Add project-wide `COMMENTAIL_EMAIL` settings for an independent Django email
  backend, constructor options and sender while preserving shared Django mail
  when no override is configured. Validate configuration without constructing
  or contacting the transport; keep provider response text out of queue errors.
- Preserve the existing outbox, retries, leases, access checks and SMTP timeout
  limits. Pending jobs use the active configuration at processing time; explicit
  transport failures never fall back to the shared backend.
- Add English/Russian setup and upgrade guidance with separate SMTP and optional
  API-provider examples. No new dependency.
- Add `test_commentail_email --to` for direct transport verification without
  comments or queue jobs, with redacted errors and explicit delivery limits.
- Refuse new guest text matching enabled Reject rules in Apply rules mode before
  creating confirmation mail. Preserve private drafts, CAPTCHA and attempt limits.
- Add optional 2000-character rule reasons, lowest-ID reason priority and a
  localized fallback; apply schema migration `0019_moderation_rule_reason`.
- Export CSV reasons and accept the optional column on import. Legacy files
  preserve existing reasons; an explicitly empty cell clears one.

This is an unpublished candidate. See [1.4.0 review and upgrade notes](docs/releases/1.4.0.md)
([на русском](docs/releases/1.4.0.ru.md)).

## [1.3.2] — 2026-10-23 · Translated Site roots

- Restore Page discussions under translated Site homepages when Wagtail content
  internationalization is enabled. Apply the same Site boundary to forms,
  protected links, queued mail and recent comments while retaining live-page
  and view-restriction checks. No data migration is required for this fix.

## [1.3.1] — 2026-10-23 · Security update

- Key quota identities and submission actor/payload fingerprints with purpose-scoped
  HMAC; migrate existing records without resetting quotas or accepted retries.
- Deny Page discussions, protected links and mail outside the saved Site root.
- Limit form/recovery ticket issuance per Site/IP while preserving reading,
  submitted drafts and existing valid tickets; translate refusal in all UI languages.
- Report distinct object-adapter validation causes without private exception text.
- Clean expired CAPTCHA, guest grants, form tickets and rate events in batches
  of at most 500, committing each batch independently and preserving live records.

Migration `0018` is irreversible: stop writers and back up database/key/package
before upgrading. See the [1.3.1 upgrade notes](docs/releases/1.3.1.md).

## [1.3.0] — 2026-10-22 · Stable

- Keep bundled external CAPTCHA bindings valid for the form lifetime, allowing
  long writing before a fresh provider proof without an extra challenge.
- Hide routine refresh for external CAPTCHA widgets; offer Retry check after errors,
  while retaining arithmetic-task refresh and editable drafts.

- Review recent repeated long guest text and link bursts, including guest edits,
  with per-Site thresholds and private moderation reasons. Use bounded keyed
  fingerprints without scanning old bodies or contacting link destinations.

- Keep independent browser forms valid when another tab opens or refreshes a CAPTCHA.
  Preserve server-owned form age across draft recovery/navigation, and avoid
  submitting an incomplete external check.
- Retain rate-limit events for configured intervals longer than one hour, including
  per-Site overrides, so periodic cleanup cannot reset those limits early.
- Add opt-in Google reCAPTCHA v2 checkbox and Yandex SmartCaptcha adapters while
  retaining arithmetic/no-JavaScript defaults and custom CAPTCHA backends.
- Add hidden-field and form-age moderation signals, independent guest attempt
  budgets, adaptive/strict CAPTCHA policy and private moderator explanations.
- Keep drafts editable when CAPTCHA issuance fails. Bound external verification,
  reject invalid host claims and prevent concurrent challenge use without holding
  the Site quota lock during network requests.
- Upgrade: run migrations `0016` and `0017`, refresh static assets and review custom form and
  CAPTCHA templates. External providers require matching site-owned keys and
  JavaScript; no service is enabled automatically. Missing/blank browser headers
  can now require CAPTCHA again for remembered guests. See the configuration and
  security guides for thresholds and disabling the form timing signal.

## [1.2.0] — 2026-10-22 · Stable

- Verify Wagtail 8.0.1 in every Wagtail 8 CI stack while retaining the existing
  support bounds. Update test pins to certifi 2026.10.19 and Pillow 13.0.0 to
  address the known advisories in the previous test environment.

- Support the configured Django email backend for guest submissions and mail
  delivery without requiring SMTP settings for other backends. Keep SMTP timeout
  protection and permanent refusal handling; retry other backend failures within
  the existing budget without storing provider diagnostics.
- Add `commentail.background.process_pending(mail_limit=100)` for periodic host
  task queues, returning JSON-compatible sent/removed counts. The existing
  `process_commentail` command shares the same implementation; a separate command
  schedule is unnecessary when the host schedules this function. Retain the DB
  outbox, retries, leases and cleanup; reject caller transactions before side effects.
- Place reply cancellation beside Send comment at the bottom of the form,
  preserving native navigation, inline dismissal and focus restoration to Reply.
  Use a compact text action that reveals its button surface on hover or keyboard
  focus. Refresh static assets and review overridden reply-form templates when
  upgrading.

- Compact guest form spacing and hints, place a short math CAPTCHA input beside
  its text refresh action, emphasize submission, and explain email confirmation
  after submission in every supported language. The submit button inherits host
  text colors and paired button overrides, with no fixed light/dark palette.
- Validate numeric navigation/filter IDs before conversion, reject null bytes in
  comment text and guest names, and enforce the stored guest-email length.
  Malformed input returns validation errors instead of server/database errors;
  native draft recovery drops unsupported null bytes while retaining the rest.
- Redact capability secrets from Django logs even when the token parameter name
  is percent-encoded. Host proxy/access logs still require their own redaction.

## [1.1.0] — 2026-10-20 · Stable

- Explain failed moderation actions with a translated recovery page and a return
  link to the same list filters. Changed statuses, permissions and unavailable
  comments leave the entire bulk action unchanged, including audit and mail jobs.

- Send optional publication notices only after moderator approval of pending
  comments or author revisions. Immediate publication stays silent for the author;
  guest confirmation/edit links and reply notifications remain available.

- Keep the permission-aware Management menu on every Commentail admin page.
  Group settings and group access fields into compact sections with aligned
  controls, adjacent checkbox labels and inline validation errors.

- Preserve the comment list's search, filters and pagination through comment
  cards, single moderation and revision decisions, erasure confirmation and mail
  retries. The card's back link returns to the same selection in each tab.

- Add a selection panel above the comment list with a live count, clear selection,
  and explanations for unavailable bulk actions. Selection applies to eligible
  rows on the current page. A cog management menu, grouped advanced filters and
  action-help popover support keyboard dismissal and reduced-motion preferences.
  Controls remain available without JavaScript.
  Refresh static assets when upgrading.

- Highlight staff author names with a colored badge and add a golden crown on
  super administrators’ avatars, with a distinct golden name badge. Enabled by
  default; a per-Site switch disables both.
  Apply migration `0015_sitecommentsettings_highlight_staff` and refresh static
  assets. Existing template overrides need the new author decorations to show them.

- Require confirmation before single or bulk text erasure, showing the comment
  count and irreversible-erasure warning, with cancellation that leaves data intact.

- Add bulk hide, restore and permanent text erasure to the comment list,
  including All statuses, with per-Site permissions and status-aware selection.
  Invalid batches roll back entirely; successful actions retain list filters.

## [1.0.0] — 2026-10-19 · Stable

The feature set is frozen at 0.2.0 Beta. This release introduces the documented
stable API and compatibility policy; runtime, dependencies and migration files
are unchanged from 0.2.0. Live-site verification of published 0.2.0 is recorded
in the [verification guide](docs/wiki/Example-and-testing.md#reported-live-site-verification-020).
The documented integration surface now follows semantic versioning and the
stated deprecation policy. Direct upgrade and backup-restoration rehearsals
cover 0.1.0 and 0.2.0 on SQLite and PostgreSQL 16.

## [0.2.0] — 2026-10-19 · Beta

Changes from **0.1.1 → 0.2.0**.

### Added

- `commentail_recent` template tag for latest published comments with a limit,
  exact Page filter, optional replies and host-owned markup. Selection enforces
  visitor access, Site isolation and hidden-discussion settings; results contain
  plain presentation fields and comment permalinks without private model data.

- Grouped Comments settings in the Wagtail Page editor, with site inheritance
  and existing save/publication behavior preserved.
- Russian README included in the source distribution.

- Minimal HTML emails for all five notification types, with host Site names,
  explanatory copy, labelled action links and equivalent plain text in all six
  supported languages. Revision decisions have distinct subjects and explanations.

- German (`de`), French (`fr`), Spanish (`es`) and Brazilian Portuguese (`pt-br`)
  translations for public forms, validation/action messages, moderation/settings,
  delivery screens and all five notification email types, including revision decisions.
- Source-coverage and compiled-catalog checks for every shipped locale, plus
  regression checks for recipient-language mail delivery and English fallback.

### Fixed

- Bounded and indexed recent-comment reads, batched Page access checks and reused
  target URLs. Discussion rendering groups reply counts and avoids per-comment
  target/settings/revision queries; moderation totals use a shared aggregate.
- Whole-word rule matching avoids a rule-by-text-position scan. Cleanup locks
  only expired unconfirmed candidates; worker claims preload authors/revisions.
- The moderation Page filter uses Wagtail's searchable chooser instead of loading
  every discussion Page into its HTML. Added reproducible synthetic load checks.

- Email copy distinguishes revision approval from public visibility, explains
  editing cutoff for replies awaiting moderation, and uses contextual action
  labels without promising new replies in read-only discussions.

- Generated author labels in reply emails use the recipient's saved language,
  including the generic account name, instead of the mail worker's language.

### Upgrade notes

- Host email overrides keep precedence; review
  both MIME alternatives and any custom subject/body wording when upgrading.
- Enable the desired language through the host site's Django language settings;
  use `pt-br` for Brazilian Portuguese. Commentail's gettext directory is `pt_BR`.
- Documentation remains in English and Russian.
- Run migration `0014_reading_indexes` for publication/thread, active CAPTCHA and
  rate-cleanup indexes, then recollect static files. Index builds may block writes
  on large tables; SQLite also rebuilds the rate-event table. See
  [performance and migration guidance](docs/wiki/Performance.md).

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

[1.0.0]: https://github.com/hardcodd/Commentail/compare/v0.2.0...v1.0.0
[0.2.0]: https://github.com/hardcodd/Commentail/compare/v0.1.1...v0.2.0

[1.1.0]: https://github.com/hardcodd/Commentail/compare/v1.0.0...v1.1.0

[1.3.1]: https://github.com/hardcodd/Commentail/compare/v1.3.0...v1.3.1
[1.3.0]: https://github.com/hardcodd/Commentail/compare/v1.2.0...v1.3.0
[1.2.0]: https://github.com/hardcodd/Commentail/compare/v1.1.0...v1.2.0
