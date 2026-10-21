# Stability and public API

**Applies from [1.0.0](https://pypi.org/project/commentail/1.0.0/).** Version 1.0.0
freezes the 0.2.0 feature set and starts the compatibility policy below. It adds no runtime
features or migrations beyond 0.2.0.

## Supported integration surface

- Django app `commentail`, `commentail.urls`,
  `commentail.middleware.CapabilityHeadersMiddleware` and optional
  `commentail.public.csrf_failure`.
- Template library `commentail_tags`: `commentail(target)`, `commentail_css()`,
  `commentail_js()`, `commentail_asset(name)`,
  `commentail_json_ld(structured_comments)` and
  `commentail_recent(limit=5, page=None, include_replies=True) as variable`.
  Pass the widget's structured context directly to the JSON-LD tag; constructing
  internal serializer objects is outside this contract.
- Documented `COMMENTAIL` settings, defaults, types, allowed values and host
  inheritance in [Configuration](Configuration.md).
- Documented callbacks, frozen `commentail.avatars.CommentContext`,
  `commentail.outbox.GuestRecipient` and `commentail.security.CaptchaTask` in
  [Callbacks](Callbacks.md). Frozen wrappers do not make their Django objects immutable.
- Registered object adapters and `commentail.objects.get_object_discussion(request, obj)`
  in [Object adapters](Object-adapters.md). The result guarantees `.pk`;
  `ObjectAccessError` and `ObjectAdapterError` remain available from that module.
  Its other ORM attributes are not public API.
- `process_commentail` with no required custom arguments. Command stdout is
  human-readable and is not a machine interface.
- `commentail.background.process_pending(*, mail_limit=100)`
  and its `ProcessingResult` dictionary keys `sent` and `removed`, documented in
  [host task integration](Email-and-worker.md#use-the-host-task-queue).
- Documented override paths, context fields and JS hooks in
  [Templates](Templates.md) and [Template contract](Template-contract.md);
  CSS custom properties and documented selectors in [Styling](Styling.md).
- [Recent-comment result fields and access rules](Recent-comments.md),
  [structured data](Structured-data.md), moderation/editing semantics, Site
  isolation, inherited settings and privacy rules described by the guides.
- CSV columns `phrase,action,enabled`, UTF-8 and idempotent upsert behavior in
  [Rules and CSV](Rules-and-CSV.md).

## Links and internal interfaces

Reverse URLs by their `commentail` names: `discussion(page_id)`, `submit(page_id)`,
`object_discussion(discussion_id)`, `object_submit(discussion_id)`,
`edit(identifier)`, `resend(identifier)` and `action(purpose)`. The host chooses
its URL prefix. Existing `#commentail-<id>` anchors remain valid. Issued protected
links retain their original expiry, subject to security revocation and access changes.

Internal selectors/services, ORM models and SQL schema, token/cookie formats,
query parameters, POST/AJAX wire formats, admin templates and JavaScript functions
are not extension APIs. Use generated URLs and opaque form/window keys rather
than reproducing their formats. Undocumented classes and `data-*` attributes are
not implicitly public. This does not remove data-migration or issued-link guarantees.

## Versioning from 1.0

| Release | Compatibility rule |
| --- | --- |
| Patch 1.0.x | Bug/security fixes; no planned breaking contracts, changed defaults or new feature scope |
| Minor 1.x | Additive, backward-compatible features, optional fields/settings/parameters; existing calls keep their meaning |
| Major 2.0 | Breaking API/default/support changes, with migration instructions |

Ordinary API removals happen only in a new major, after warnings in at least two
minor releases and at least six months from the first warning. Documentation gives
the replacement and removal plan; Python warnings are used where practical. This
is a transition period, not a promise of a release schedule or indefinite support.
Confirmed security vulnerabilities may require urgent behavior changes, higher
minimum dependency patches or token revocation; release notes explain the impact.

## Supported environments and upgrades

The frozen support matrix is Python 3.12–3.14; Wagtail 7.4.3+ within 7.4 with
Django 5.2/6.0, and Wagtail 8.0.x with Django 5.2/6.0/6.1; file SQLite and
PostgreSQL 16. Added support may appear in a minor; planned removal requires a
major. New upstream versions are not supported automatically.

Direct upgrades from 0.1.0 to the first stable release and forward upgrades within
a stable major must preserve retained data and documented behavior. Backups are
required. Patch/minor migrations may change schema while preserving that contract.
Reverse migrations, running an old wheel against a new schema and zero-downtime
upgrades are not promised. Restoring a backup loses later writes and can replay
mail that was pending in the snapshot. See [Deployment](Deployment.md).

## Verification limits

Tests cover the declared framework/database matrix. Prior acceptance covered
installed desktop browsers, responsive viewports and selected VoiceOver scenarios;
historical checks additionally covered Chrome 142 on macOS and Windows ARM64
and Firefox 140 ESR on Windows ARM64, with Chrome x64 under emulation.
A full physical-device/accessibility matrix and native Windows x64 remain unverified.
Six languages are included; native-speaker review and a complete email client matrix are not claimed. Synthetic performance checks do not guarantee
capacity on an arbitrary host. Each site must verify its theme, access and delivery.

[Documentation home](Home.md)
