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

## Later: reject hard-rule matches before guest email confirmation

When Apply rules is active, reject guest submissions matching an enabled Reject
rule before creating a confirmation email. Show the sender an administrator-defined
reason for the rule and preserve the draft for correction and resubmission,
with or without JavaScript. Keep existing submission protection and attempt limits;
early refusal should create neither confirmation nor rejection mail.

Duplicate text, multiple links and other soft signals keep their existing email
proof and moderation flow. Reason selection for multiple matches, the fallback
for an empty reason and CSV compatibility remain to be defined before implementation.

This is planned future work, explicitly outside the current anti-spam update.
The owner will choose its target release separately; no version or date is assigned.

## Later: most-discussed threads

A ranking of threads by discussion activity is deferred. No API, release number
or delivery date has been agreed. The recent-comments API does not supply this ranking.

Additional locales have no agreed list or date. Native-speaker review of the
new catalogs remains a separate quality step; automated coverage does not
replace language review. See [language configuration](Configuration.md#languages).

[Documentation home](Home.md)
