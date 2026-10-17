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
Headers are forgeable, never identity or a replacement for CSRF. Signed-in authors
are unaffected by these guest-only signals. An empty signal list disables them only.

Rate limits use the direct peer by default. Add only actual immediate proxy networks
to `TRUSTED_PROXIES`; never trust every internet address. Forwarded headers influence
client IP only through trusted peers. Quotas are Site-wide with independent counters.

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

The worker erases expired unconfirmed comments/proofs. Published comments have no
automatic retention policy in 0.1.0. Backups, CSV exports, SMTP logs and host analytics
have separate retention. These controls do not establish legal compliance for a site.

## Text and links

HTML/Markdown are not rendered. If enabled, clickable links accept HTTP(S) only and
use nofollow, ugc, noopener and noreferrer. Preserve escaping in custom templates.
No third-party CAPTCHA, external avatar service, CDN or analytics is required.

---

[← Object adapters](Object-adapters.md) · [Documentation home](Home.md) · [Deployment →](Deployment.md)
