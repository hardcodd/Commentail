# Commentail

Comments for Wagtail CMS, under active development. The first release targets
Wagtail 7.4 LTS (7.4.3 or later) and Django 5.2 on Python 3.12–3.14. It has not been released on PyPI.

The source now includes a Wagtail moderation section and server-rendered widget:
guest email verification, registered authors, direct replies with one visual
nesting level, pending author revisions, safe links, site/page policies and group
capabilities. Moderators approve, reject, hide, restore or erase text; they cannot
rewrite another author's comment.

The local 0.1.0 candidate is prepared for review. Previous browser releases,
physical mobile devices and independent owner acceptance remain unverified.
No production integration is included.

## Integration

Use Python 3.12–3.14 and a virtual environment:

```sh
pip install .
# Optional PostgreSQL driver:
pip install '.[postgres]'
```

Add `commentail` and `wagtail.contrib.settings` to `INSTALLED_APPS`. Keep the host
session, authentication, messages and CSRF middleware. Place
`commentail.middleware.CapabilityHeadersMiddleware` before CSRF middleware;
widget pages contain personal form state and receive `private, no-store`.
Email-action responses also use `Referrer-Policy: strict-origin`: referrers never
contain the secret path/query, while native forms retain the origin needed for
CSRF validation. Preserve this policy in overridden action templates; a global
`no-referrer` meta tag can break confirmation, editing and unsubscribe forms.
The Django template request context processor is required.
Optionally set `CSRF_FAILURE_VIEW = "commentail.public.csrf_failure"` to preserve
a rejected submission draft and show a fresh form for explicit resubmission.
Fetch receives HTTP 403 with the preserved draft. Browser document submissions
return to the host with a private draft and an explicit resubmission notice; no
comment is accepted. Other host endpoints keep Django's default failure view. Logging in rotates CSRF tokens, so forms opened before login can
need refreshing. Separate localhost projects should use distinct session/CSRF
cookie names because cookies are shared across ports.

Include `path("commentail/", include("commentail.urls"))` before Wagtail's page
catch-all routes. Run `python manage.py migrate` and `python manage.py check`.
Guests require a configured SMTP backend and host. Registered authors without
email can comment but receive no mail. The library uses existing site accounts
and does not supply a registration/login system.

## Templates and styles

Place resource tags once in the host template and the widget where needed:

```django
{% load commentail_tags %}
{% commentail_css %}
{% commentail_js %}
{% commentail page %}
```

For Wagtail `Page` subclasses, compiled inheritance
and include chains control a request-local Comments tab in the page editor.
Resource tags alone do not enable it. Dynamic dependencies require the
`GET_COMMENT_TEMPLATES` callback. Page overrides save with the standard page
action and take effect immediately, independently of Page revision/publication.

Host templates at the same paths override package templates. Public partials
are `commentail/block.html`, `comment.html`, `replies.html`, `form.html` and
`captcha.html`; the inline editor is `commentail/edit-form.html`.
Email-action pages extend `commentail/base.html`;
override that base to use the host layout, or its `extra_head` block to add local
styles. Their standalone layout uses system fonts and neutral light/dark colors.
The `commentail-document` body scopes these defaults away from embedded widgets;
`--commentail-document-background` and `--commentail-document-shadow` customize
the document, alongside the usual widget properties. These pages are also
overridable. Preserve CSRF, submission keys, target identifiers and server checks.

The widget inherits the embedding container's text color, font, font size and
line height. Its background is transparent; fields, buttons and separators use
subtle translucent tones of the current text color. This follows the site's own
light/dark switch and decorative backgrounds without JavaScript or an OS-theme
guess. Without `color-mix()` support, controls retain transparent backgrounds and
solid current-color borders. Generated avatar colors remain independent.

Classes use `commentail-*`; custom properties use `--commentail-*`. Set properties
on the widget or an ancestor such as `:root`; load class overrides after the
package stylesheet. For example, map the site's own accent token explicitly:

```css
:root {
  --commentail-color-accent: var(--site-link-color, #245a86);
  --commentail-border-radius: .4rem;
  --commentail-avatar-size: 2.25rem;
}
```

| Property suffix (after `--commentail-`) | Default |
| --- | --- |
| `color-text`, `font-family`, `font-size`, `line-height` | Inherited from the container |
| `color-accent`, `color-muted`, `color-error` | Current/inherited text color |
| `color-surface` | Transparent widget background |
| `color-border` | Text-color tint; stronger on controls |
| `color-input-surface` | 3% text-color tint |
| `color-button-text` | Accent or inherited text color |
| `color-button-surface`, `color-button-hover` | 8% / 15% button-text tint |
| `color-control-surface`, `color-control-hover` | Quiet actions: transparent / 8% text-color tint |
| `color-menu-surface`, `color-menu-text` | Action popup: browser canvas with a subtle tint / canvas text |
| `border-radius`, `avatar-size` | `.75rem` / `2.5rem` |
| `spacing`, `max-width` | `1rem` form spacing unit / `48rem` widget limit |
| `input-min-height`, `input-max-height` | `6rem` / `24rem` |

The host must provide readable foreground/background contrast. A busy photograph
or conflicting global `!important` rules can require explicit overrides; the
widget cannot safely infer a brand palette or repair the host's contrast.
For a filled accent button, set both `color-button-surface` and
`color-button-text` to a contrasting pair, and set `color-button-hover` as needed.
Standalone email-action documents need the same host theme via
overridden page templates; they cannot inherit CSS from a different document.

Public forms/links work without JS;
JS enhances submission, reply selection, reply expansion, pagination and CAPTCHA
refresh by replacing the matching discussion block with server-rendered HTML.
Reading/navigation preserves the current draft. Loading blocks parallel requests;
network failures keep the draft and submission key for an explicit retry, without
automatically replaying a POST. Email confirmation and unsubscribe pages use ordinary forms.
Autoheight and broken-avatar fallback are included; horizontal textarea resizing
is disabled. No mandatory frontend framework or external CDN is used.
Keyboard navigation moves focus to newly loaded messages after expansion or
pagination, to the reply field when choosing an addressee, and to error messages
when a request fails. CAPTCHA refresh focuses the new answer field. The widget
declares its translation language independently of the host document's language.
Overridden widget templates should preserve `data-discussion`,
`data-commentail-navigation`, the `.commentail-form` / `.commentail-edit-form`
classes and the localized
`.commentail-network-error` element to retain these enhancements.

Lists use cumulative batches of 20 and signed snapshot windows. New publications
appear after refresh; target links expand the addressed thread and include the
specific reply even beyond the first reply batch.

Successful email-confirmation and guest-revision POSTs redirect to the host
comment with HTTP 303. Email confirmation still requires its explicit action
form; GET never confirms or changes a comment. Editing opens beneath the comment
inside its host article, including without JavaScript. Guest edit links exchange
their capability for a browser-session proof and redirect into that article;
no capability appears in its URL or form. Every save rechecks access, expiry and
editing eligibility. Legacy edit GETs also redirect; no standalone edit document
or template exists. Validation retains a private draft and error in the article.
Reply uses a quiet text control; eligible authors find Edit in the comment's
ellipsis disclosure, which also works without JavaScript. With JavaScript,
Escape/outside click closes the menu. Cancel removes the editor and returns focus
to the visible ellipsis trigger; saving keeps
the independent main/reply drafts and focuses the updated comment.

With JavaScript, Reply opens a single composer directly below the addressed
comment, including replies to replies. The main form keeps its separate draft.
Switching the addressee keeps the reply draft; Cancel removes the reply form
from the DOM and returns keyboard focus to its Reply link. Updates preserve
expanded threads, their loaded batches and the reader's position. Submission
reveals the exact accepted message in its thread; its email notice stays beside
it. Your pending replies appear beneath their visible addressee. Validation and
CAPTCHA refresh keep the composer beside its addressee. Without JavaScript,
Reply uses the ordinary server-rendered form at the top of the discussion.

Comment permalinks and successful submission/edit returns point to the host
Page or registered object's URL, keeping the addressed comment in its discussion.
Opening a discussion service URL as a browser document redirects to that host
and retains reading state, including reply pagination. Service reads, CAPTCHA
refresh and validation/CSRF errors for fetch return only the widget HTML fragment,
without a standalone document or bundled asset tags. The standalone discussion
page/template is removed. Browser validation errors and CAPTCHA refresh return
to the host as well,
with a session-bound, expiring database draft. Only a ticket ID enters the URL,
not text, names or email. Drafts survive reload until acceptance or expiry; the
worker removes expired form tickets. Up to five recovery tickets are retained
per browser. Non-document fragment requests retain inline errors. A failing object
URL handler cannot redirect browser navigation and produces a neutral 404.

## Administration

The Comments menu provides a site-scoped queue, search/date/page/status filters,
individual/bulk moderation, revision comparisons and mail error retry controls.
The Email delivery screen lists jobs by Site and status, with 25 jobs per page.
View grants scope both source and recipient; moderation grants permit explicit
retries of failed deliveries. Expired or inaccessible messages cannot be resent.
Status tabs count only matching comments on permitted sites. The queue includes
pending author revisions; bulk selection applies only to pending comments the
moderator may review. Settings use Wagtail's accessible field/error rendering.
The default queue includes pending author revisions. Revision decisions are
individual; bulk actions apply to pending comments.

Site settings control open/read-only/hidden mode, four moderation policies,
author access, text length, clickable links and publication/rejection emails.
The site-only **Send emails** switch (`email_enabled`) defaults to `True`. Turning
it off blocks all comment emails and cancels queued mail before delivery; pages
cannot override it. Guest submission is unavailable while mail is disabled or
SMTP is not configured. Registered users can continue commenting without email.

Public submissions automatically subscribe authors with an email address when
site email and SMTP are enabled. There is no subscription checkbox or idle-form
hint; after acceptance, a one-time notice says “We’ll email you about replies.”
Every reply email retains its per-comment unsubscribe link. Existing comments and
previous opt-outs are never subscribed retroactively.
Pages inherit or override each value. Word/phrase rules are project-wide;
rejection takes precedence over review when several rules match. The rule list
supports phrase search, action/enabled filters and 25 records per page, retaining
filters across pages. Adding and editing use separate forms; all rule endpoints
require the project-wide rules capability.

Import/export buttons support bulk rule management. Export downloads all rules
as UTF-8 CSV with a BOM, independent of active list filters. The columns are
`phrase`, `action` (`review` / `reject`) and `enabled` (`1` / `0`; import also
accepts `true` / `false`). Import accepts comma or semicolon separators and
preserves quoted Unicode phrases, commas and line breaks:

```csv
phrase,action,enabled
spam,review,1
unwanted phrase,reject,1
```

Import adds new phrases and updates action/enabled on exact phrase matches;
unmentioned rules remain unchanged. Reimporting the same file is idempotent.
Invalid rows, duplicate phrases in the file or ambiguous existing matches abort
the entire import and show a row error. Spreadsheet-sensitive phrase prefixes
are escaped with an apostrophe on export and restored on import; literal leading
apostrophes are doubled. Use the exported format when transferring such phrases.
Default limits are 5 MiB and 20,000 rules per import, overridable only in
`COMMENTAIL["default"]` as `RULES_CSV_MAX_BYTES` and `RULES_CSV_MAX_ROWS`.

The standard Wagtail group create/edit form includes a Comment permissions by
site panel: viewing, moderation, hide/restore, text erasure, settings and shared-rule
management. Wagtail's normal group create/change permissions authorize this panel.
Changes save with the group; duplicate sites and invalid rows prevent saving.
The separate Comments group-access editor remains superuser-only and edits the
same records. Commentail users also need Wagtail admin access. Page configuration
additionally requires normal page-edit rights.
Direct action URLs enforce the same boundaries as their controls.

## Objects outside Wagtail Page

Explicitly register ordinary Django models in the project-wide
`COMMENTAIL["default"]["OBJECT_ADAPTERS"]` dictionary:

```python
COMMENTAIL = {
    "default": {
        "OBJECT_ADAPTERS": {"shop.Product": "myproject.comments.ProductAdapter"},
    },
}
```

Adapters are stateless classes constructed without arguments:

```python
from django.http import HttpRequest
from wagtail.models import Site
from shop.models import Product


class ProductAdapter:
    def get_site(self, obj: Product, request: HttpRequest) -> Site:
        return obj.site

    def can_view(self, obj: Product, request: HttpRequest) -> bool:
        return obj.is_public or request.user.is_staff

    def get_url(self, obj: Product, site: Site) -> str:
        return obj.get_absolute_url()
```

Use the same `{% commentail product %}` tag and resource tags. Registration
supports concrete, non-proxy models with integer, UUID or string primary-key
fields; stored keys must be nonempty and at most 255 characters. Model, key and
Wagtail Site identify a discussion independently. Unregistered models are denied.
The adapter's saved Site must match the Site resolved for the current request.
Keep the host object's own view protected by the same access policy.

Every direct comment request rechecks registration, target existence, Site and
visitor access, including form replays and author edits. Adapter errors fail
closed with neutral visitor output and type-only server diagnostics; stored
comments/settings are retained. `CommentContext.target` is the actual object.
`get_url` must return an absolute HTTP(S) URL or a root-relative path.

The Comments section includes **Object discussions**, a searchable, paginated
list of existing discussions and a separate settings card with the same Site
inheritance choices as Pages. The Site settings grant authorizes this card;
no fields are injected into the host model editor. Rendering the tag creates
the discussion after access checks; Python integrations may also call
`commentail.objects.get_object_discussion(request, obj)`.

Account email delivery checks the adapter using a worker-created GET request
with the recipient's account, Site host, language and an empty session. Policies
requiring browser-only proof cannot authorize mail through this request. Guest
mail requires `CAN_SEND_GUEST_EMAIL` for registered objects; that callback proves
offline access. The adapter must still resolve the stored Site correctly.

Normal instance and queryset deletion through Django's runtime ORM removes all
related discussions, replies, revisions, subscriptions, tokens, form records,
mail and moderation events across Sites. Cleanup also works after removing the
adapter registration. Raw SQL and historical-model data migrations bypass this
runtime cleanup and must explicitly remove their discussions.

## Python settings and callbacks

Technical options inherit library defaults, `default`, then the server-selected
Wagtail Site hostname. Partial sections inherit omitted values:

```python
COMMENTAIL = {
    "default": {
        "AUTHOR_LIMIT_PER_HOUR": 20,
        "GET_AVATAR": "myproject.comments.get_avatar",
    },
    "www.example.org": {"AUTHOR_LIMIT_PER_HOUR": 40},
}
```

Keys/defaults are defined in `commentail.config`. Unknown keys, invalid types or
intervals and unimportable handlers fail system checks. Current callback contracts:

- `CAPTCHA_BACKEND`: an import path to a class with no-argument construction.
  `create(request, site) -> CaptchaTask` and
  `verify(request, site, challenge_id: str, answer: str) -> bool`.
  Import `CaptchaTask` from `commentail.security`: `id` is a string/UUID
  identifier (up to 255 characters), `template` is a resolvable template name,
  `data` is a dictionary of public string values. Keep answers/private provider
  state on the server. The template receives `captcha.data`; its form control
  submits `answer`. The library issues a separate browser ID and sends the
  original provider ID only to verification. Site/session binding, expiry,
  attempts, refresh invalidation, creation quotas and successful single use
  remain enforced by the library. The backend owns expiry/cleanup of any
  separate private provider state. Changing the backend invalidates prior tasks;
  provider errors fail closed with neutral UI messages. `None` uses arithmetic.

- `GET_AVATAR`: `get_avatar(context, request) -> str | None`, returning an image
  URL or using generated initials/gradient. Frozen `CommentContext` contains
  `id`, `display_name`, `user`, `site`, `target`, without guest email/internal Comment.
- `GET_AUTHOR_NAME`: `get_author_name(user, request) -> str`, for the registered
  author's current name. Name/avatar failures fall back to library defaults.
- `GET_COMMENT_TEMPLATES`: `get_comment_templates(page, request) -> list[str]`,
  enumerating dynamic dependencies. Presence of the widget tag still controls
  connection. Resolver failures are diagnosed without breaking the page editor.
- `CAN_SEND_GUEST_EMAIL`: `can_send_guest_email(recipient, target, site) -> bool`,
  proving guest access to restricted pages and registered non-Page objects
  without a browser request. A failure
  denies delivery and becomes a job error. `GuestRecipient` contains `email`,
  `name`, `confirmed_at`; the latter can be `None` for verification mail.

`services` is a trusted domain API, not an HTTP admission boundary. Built-in
handlers use `admission.accept_request` for access, guest proof/CAPTCHA,
session-bound submission keys and site-wide author/IP limits. An email address
alone never proves ownership. Pending content is visible only to its author,
in the submitting browser or by a protected view link.

### Supplemental guest request signals

`GUEST_REQUEST_CHECKS` is a list in `COMMENTAIL["default"]` or a hostname override.
The default is `["missing_user_agent", "cross_site"]`:

- `missing_user_agent`: absent or whitespace-only `User-Agent`.
- `cross_site`: `Sec-Fetch-Site` explicitly equal to `cross-site`.

Any enabled match sends guest comments to moderation after email verification;
a matching rejection rule still takes precedence. Missing Fetch Metadata alone
is not suspicious. An empty list disables these signals. Unknown names, invalid
types and duplicates fail configuration checks. These client headers are
forgeable; signals complement CAPTCHA, email proof and quotas. They never disable
CSRF/origin checks or object access, and do not affect signed-in authors.

## Mail and cleanup

Schedule `python manage.py process_commentail` once per minute. It processes the
DB outbox and expires unconfirmed comments without Redis/Celery. The 24-hour
confirmation deadline starts at acceptance. Retries/owner resends reuse the
original job/token without extending it. Guest publication creates a separate
editing-link email. Editing lasts 15 minutes from publication and ends permanently
when a direct reply is accepted, even before that reply is moderated.

SMTP runs outside state-transition transactions. Temporary/uncertain failures
retry after 1, 5 and 15 minutes; permanent refusals require explicit retry.
Leases prevent concurrent claims, but uncertain results can cause duplicate mail;
a stable Message-ID does not guarantee exactly-once delivery. Hidden discussions
defer mail. Lost access, disabled subscriptions and expired links cancel it.
Reply emails contain author names and links, never comment text.

The submitting guest browser shows a private confirmation-mail status: queued,
sending, sent, automatic retry, failed or unavailable, plus the original deadline.
Sent means the configured mail backend accepted the message, not inbox delivery.
SMTP diagnostics, email addresses and tokens are never included in that status.
Resend is offered only before expiry while no worker is sending the message.
Status updates appear on reload; normal resend forms also work without JavaScript.

### Overriding email templates

Place overrides in your project's template directory, ahead of Commentail in
Django's template loader order. For each kind (`confirm`, `edit`, `published`,
`rejected`, `reply`), the stable paths are:

- `commentail/emails/<kind>_subject.txt`: required nonempty, single-line subject
  (surrounding whitespace is stripped).
- `commentail/emails/<kind>.txt`: required plain-text body.
- `commentail/emails/<kind>.html`: optional HTML alternative; absent by default.

Templates render under the job's saved language, without request context
processors. The public context contains only `kind`, `author_name`, `site_name`,
`site_url`, `target_url`, `action_url`, `view_url`, `reason`, `is_revision` and
`expires_at` (an aware datetime). URLs are absolute. `action_url` is the protected
confirmation/edit/unsubscribe link when applicable; `view_url` is set only for
confirmation mail. `reason` is set only for rejection. `is_revision` distinguishes
author-revision decisions, which share the publication/rejection templates.
No internal comment/job/user objects, comment or revision text, or recipient
email are supplied. Reply notifications must continue to contain only metadata
and links, without reply text or excerpts, in every MIME alternative.

Use `{% autoescape off %}` around plain-text templates so names and URL query
strings remain literal. Keep HTML autoescaping enabled. For example:

```django
{% load i18n %}{% autoescape off %}{% trans "Confirm your email" %}

{{ action_url }}
{% endautoescape %}
```

Missing required templates, invalid template syntax and invalid subjects fail
that job safely; details in the delivery admin are technical error types only.
Other queued messages continue processing. Correct the override, then retry the
failed message from the admin while its original link remains valid.

Confirmation, unsubscribe and status links show action pages; guest edit links
open the inline editor in the host article. Comment changes require POST/CSRF.
Action-token secrets are hashed in
storage. Queued links derive from a random nonce and host SECRET_KEY; rotation
prevents regenerating old queued links. Protect token queries in custom proxy
logs/error reporters. The package redacts them in Django's development-server
logger and action error context.

## Development checks

The GitHub Actions workflow defines tests for Python 3.12, 3.13 and 3.14
with SQLite and PostgreSQL 14, plus
JavaScript, lint, migrations, translations and the source/wheel distributions.
`requirements-test.txt` pins the acceptance environment; it is not a host-site
production lockfile. Install it before running the checks below.

```sh
python -m django test tests --settings=tests.settings
# Optional development check with Node.js (no npm dependencies):
node --test tests/test_*.js
```

Default tests use synthetic in-memory SQLite. Set `COMMENTAIL_TEST_SQLITE` to a
fresh disposable file for writer-concurrency tests. PostgreSQL checks require a
dedicated synthetic cluster/user:

```sh
COMMENTAIL_TEST_POSTGRES=1 PGUSER=commentail_test PGHOST=127.0.0.1 PGPORT=55432 \
  python -m django test tests --settings=tests.settings
```

Supply PGPASSWORD securely in the environment. The runner creates/destroys
`commentail_synthetic_tests`; never use a production cluster.

Checks cover transitions/concurrency, CSRF/admission, site rights, owner visibility,
guest confirmation/editing, mail claims, template detection, registered-object
access/isolation/cleanup and Page create/edit saving. All 228 server tests passed
from the installed wheel outside the source checkout on Python 3.12.14, 3.13.15
and 3.14.7 with file SQLite and PostgreSQL 14.24, Wagtail 7.4.3 and Django 5.2.18.
All six combinations include writer-concurrency checks. All 29 JavaScript tests,
lint, migration drift and translation checks passed. The fresh source-distribution
suite also passed (four concurrency/file-only checks skipped with in-memory SQLite).
The source distribution installs in a fresh environment; its example was checked
through migrations, repeated bootstrap, worker, static collection and both widgets.

The minimum supported Wagtail patch is 7.4.3. Earlier 7.4 patches are excluded
because of upstream security fixes; the test pin and installed environments use
7.4.3. See the [Wagtail 7.4.3 release notes](https://docs.wagtail.org/en/stable/releases/7.4.3.html).

Native browser checks cover Safari 27.0.1, Chrome 155.0.8059.40,
Yandex Browser 26.8.3.1016 and Firefox 158.0. Recent regression checks exercised
inline reply forms, cancellation/focus and independent drafts; Safari also covered
the HTML reply/cancel fallback without scripts. Earlier passes covered moderation,
revisions, CSV and responsive layout. A real SMTP guest chain reached an external
inbox, including confirmation, publication, editing, reply notification and unsubscribe.
This is a bounded local acceptance run, not a guarantee of delivery to every provider.
After the 7.4.3 update, targeted reply/cancel/thread/draft checks passed in all
four installed browsers. Publication, inline edit, author menu and immediate
post-snapshot reply placement were checked in the in-app browser. These targeted
checks do not repeat every earlier native-browser scenario.
Previous browser versions, physical mobile devices, a hosted CI run and independent
owner acceptance remain outstanding. Upstream Treebeard warnings are not suppressed.
No production deployment or public release is claimed.

MIT license. See [LICENSE](LICENSE).


## Runnable example

The source distribution includes [a local Wagtail project](example/README.md)
with Page and ordinary Django model integrations, tagged templates and an
idempotent bootstrap command. It uses
a separate local database and creates no predefined admin account. Follow its
README to run migrations, create your admin and enable test SMTP if needed.
