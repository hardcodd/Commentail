# Commentail roadmap

This page records planned directions. A target release or delivery date is only
listed once agreed. Planned work is not part of the published package.

## Released in 1.3.0

Version 1.3.0 adds guest form checks, attempt budgets, optional Google/Yandex
CAPTCHA and review signals for repeated text and link bursts, including guest
edits. It preserves editable drafts and independent forms while keeping external
verification mandatory when selected. See [changes and upgrade steps](Release-1.3.0.md).

## Released in 1.2.0

Version 1.2.0 includes configurable Django email backends, integration
with the host task queue and compact reply cancellation beside Send comment.
The guest form is also more compact, with a short CAPTCHA field and clearer email
confirmation guidance. All three planned features have been implemented and accepted.
The pre-release audit added input/logging fixes and verified Wagtail 8.0.1 with
updated test dependencies across the full supported matrix.

See [1.2.0 changes and upgrade guidance](Release-1.2.0.md) and
[email/background setup](Email-and-worker.md).

## Released in 1.1.0

The accepted moderation improvements include bulk actions, erasure confirmation,
clearer selection and filters, preserved navigation and understandable errors.
Staff highlighting, compact settings and publication notices only after moderation
are included. See [1.1.0 scope and upgrade steps](Release-1.1.0.md).

## Released in 1.0.0

Version 1.0.0 establishes the [stable API and compatibility policy](Stability.md)
with the 0.2.0 feature set. It adds no runtime changes, dependencies or migrations.
See [1.0.0 release and upgrade notes](Release-1.0.0.md).

## Released in 0.2.0 Beta

Version 0.2.0 contains recent comments with filters and host-owned markup,
indexed/batched database reads, grouped Page settings, HTML emails and four
additional languages (German, French, Spanish and Brazilian Portuguese).
English and Russian remain available; documentation remains in those two languages.

**Status:** included in 0.2.0 Beta.
See [0.2.0 release scope and upgrade steps](Release-0.2.0.md),
[version history](Changelog.md) and [performance guidance](Performance.md).

## Implemented in 1.4.0

Version 1.4.0 adds an independent Django email backend, constructor options and
sender through the project-wide `COMMENTAIL_EMAIL` dictionary. For example,
comment emails can use a provider's HTTP API while the rest of the site continues
using SMTP, within the same application and worker configuration. Without an
override, Commentail continues using the project's shared backend and sender.
Version 1.4.0 also adds a direct test-mail command and early guest refusal for
enabled Reject rules, with optional reasons and backward-compatible CSV import.
See [rules and CSV](Rules-and-CSV.md); migration `0019` adds the reason field.

Version 1.4.0 is published. See the
[configuration reference](Email-configuration.md) and
[upgrade notes](Release-1.4.0.md).

## Later: visual Markdown editor and emoji

Add a visual comment editor based on Markdown, without a source view or a
source-editing toggle. Readers compose and format comments through the editor UI.
This is future work, outside 1.4.0, with no target version or date.

Emoji support is also planned. The formatting subset, storage/rendering and
sanitization contract, editing and no-JavaScript behavior, accessibility, editor
dependency and emoji interaction remain to be defined before implementation.
Emoji do not imply the separate Like/Dislike reaction feature.

## Later: most-discussed threads

A ranking of threads by discussion activity is deferred. No API, release number
or delivery date has been agreed. The recent-comments API does not supply this ranking.

Additional locales have no agreed list or date. Native-speaker review of the
new catalogs remains a separate quality step; automated coverage does not
replace language review. See [language configuration](Configuration.md#languages).

[Documentation home](Home.md)
