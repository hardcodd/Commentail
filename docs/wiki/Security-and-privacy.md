# Access, spam prevention and privacy

## Host access is authoritative

Every request rechecks target existence, Site and visitor permission. Direct URLs
do not bypass restricted Page/object access. Discussion identity includes the Site.
Protect your object's own view with the same policy as its adapter. Trusted Python
services are not an HTTP admission API; use built-in views for untrusted forms.

## Spam layers and proxies

Guests use email proof, replaceable CAPTCHA, account/email + IP quotas and optional
request signals. Defaults are missing/blank User-Agent and explicit
`Sec-Fetch-Site: cross-site`; missing Fetch Metadata alone is not suspicious.
Signals send guests to moderation after proof; rule rejection wins in Apply rules.
In adaptive mode, enabled header signals also require CAPTCHA from a guest with
remembered email. `GUEST_CAPTCHA_MODE="always"` checks every guest submission;
registered authors keep their existing behavior.

When an external CAPTCHA is required, JavaScript is required too. The form
explains how to proceed; no arithmetic, email-only or additional moderation-queue
fallback is offered. Lack of JavaScript does not grant a CAPTCHA exemption.
See [provider configuration](Callbacks.md#ready-to-use-providers).

Headers are forgeable, never identity or a replacement for CSRF. Signed-in authors
are unaffected by these guest-only signals. An empty signal list disables them only.

Rate limits use the direct peer by default. Add only actual immediate proxy networks
to `TRUSTED_PROXIES`; never trust every internet address. Forwarded headers influence
client IP only through trusted peers. Quotas are Site-wide with independent counters.

## Low-friction guest checks

A hidden `commentail_contact` field is excluded from keyboard navigation and the
accessibility tree. Filling it or submitting within `GUEST_FORM_MIN_SECONDS`
(default 2, 0 disables timing) flags the comment for review; it never discards it
or enforces a waiting countdown. Server-owned form issuance time cannot be chosen
by the browser. Refresh, validation recovery and enhanced reading navigation
retain the age of a live form belonging to the same browser/discussion. A new
composer starts a new window; accepted or expired forms cannot age it. Public
ticket IDs used for reading navigation convey no submission or viewing authority. Custom forms may
omit the honeypot for compatibility, but then cannot benefit from that signal.

Before CAPTCHA verification or mail creation, guest attempts have separate
Site/session and IP budgets: 10 per session/minute, 30 per IP/minute and 300 per
IP/hour. Failed proofs/validation spend this budget too. Accepted idempotent
retries bypass it after access/ticket checks. Unverified email is deliberately
not an attempt-budget identity, to avoid letting strangers exhaust another
person's quota. Existing accepted-comment, resend and CAPTCHA-issuance quotas
still apply. Background cleanup retains events for the longest configured
author/resend interval or duplicate-text window across Site overrides (at least
one hour). Configure shared-network limits for your site's actual traffic.

Moderators see translated reasons in the private comment detail view. The stored
codes are `honeypot`, `fast_form`, `missing_user_agent`, `cross_site`,
`duplicate_text` and `many_links`. They are
hints, not proof that a person is a bot; moderator approval remains available.
The `commentail.antispam` INFO logger emits Site ID and signal codes for review,
proof refusal and attempt limits; `commentail.captcha` reports provider error
class names at ERROR. A host can count these events in its existing logging
system. No comment text, email, IP, credentials or tokens are included in these
application events. These controls have not measured real-world spam reduction.

## Guest content checks

By default, guest text of at least 80 normalized characters is sent to review
when the same text was accepted on this Site during the previous hour. Comparison
uses Unicode NFKC, case folding, whitespace collapsing and removal of invisible
format characters; punctuation remains significant. The stored/displayed body
is unchanged. Short common replies are exempt. Comparison spans discussions and
guest emails on the same Site; registered authors are unaffected.

Three or more explicit HTTP(S)/www link occurrences also trigger review, even
when clickable links are disabled. Repeated links count separately. Bare domains,
email addresses and obfuscated URLs are not matched by this check. One or two
links do not trigger the default threshold. No URLs are fetched or reputation
services contacted. These are review signals, not automatic rejection/deletion;
explicit rejection rules still win under Apply rules.

Both checks also apply to changed guest author revisions. A flagged revision
waits for moderation while the published body stays unchanged; its reasons appear
in the private revision detail. Unchanged normalized text does not create another
fingerprint; it is checked for links again if the explicit link count changes.
Email proof, CAPTCHA and ordinary quotas retain their existing rules, with no
additional mail or guest steps. Idempotent retries do not create fingerprints.

Configure `GUEST_DUPLICATE_WINDOW_SECONDS`, `GUEST_DUPLICATE_MIN_LENGTH` and
`GUEST_LINK_REVIEW_THRESHOLD` per Site. A zero window/threshold disables its check.
The indexed rate ledger stores only a keyed text fingerprint, never another copy
of the body; cleanup retains it for the configured window. History starts with
newly accepted guest submissions/proposals: old comment bodies are not scanned
or backfilled. Rotating Django's `SECRET_KEY` starts a new comparison history.
The ledger expires independently of comment deletion; no comment text is retained
there. Similarity matching and domain blocklists are not provided.

## Protected forms and links

CSRF and session-bound submission keys protect mutations. A retry of an accepted
submission does not create a duplicate. Network failures preserve the key/draft
for explicit retry; JS does not automatically replay POSTs. GET never confirms,
unsubscribes or decides moderation. Guest edit links exchange a capability for
browser proof and redirect to the article without the secret in its URL/form.

Token secrets are hashed in storage. Regeneration of queued links needs SECRET_KEY;
key rotation affects pending links. Use HTTPS and redact tokens from proxy logs,
analytics and error reporting. Widget responses use private/no-store; do not serve
personalized HTML from shared caches. Preserve action documents' strict-origin policy.

## Stored information and deletion

Email is admin-only, not public and not supplied to avatar callbacks. Pending text
and rejection reasons are author/admin-only. Reply mail contains no comment text.
Action logs contain no old text copies. Hide is reversible; erase is permanent but
replies retain a placeholder. Account deletion retains messages as Deleted user,
removes stored email and cancels subscriptions/mail. Runtime ORM deletion of a
Page/registered target cascades discussions; raw SQL and historical-model migrations
must explicitly clean up related records.

The scheduled background pass erases expired unconfirmed comments/proofs.
Published comments have no automatic retention policy. Backups, CSV exports,
mail-provider logs and host analytics
have separate retention. These controls do not establish legal compliance for a site.

## Text and links

HTML/Markdown are not rendered. If enabled, clickable links accept HTTP(S) only and
use nofollow, ugc, noopener and noreferrer. Preserve escaping in custom templates.
No third-party CAPTCHA, external avatar service, CDN or analytics is required.

---

[← Object adapters](Object-adapters.md) · [Documentation home](Home.md) · [Deployment →](Deployment.md)
