# Python callbacks and custom CAPTCHA

Use import paths in `COMMENTAIL`; see [Configuration](Configuration.md). Avoid slow
remote work in render callbacks. No callback should return credentials or private text.

## Contracts

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

## Avatar example

```python
from django.http import HttpRequest
from commentail.avatars import CommentContext


def get_avatar(context: CommentContext, request: HttpRequest) -> str | None:
    if context.user is None:
        return None
    profile = getattr(context.user, "profile", None)
    image = getattr(profile, "avatar", None)
    return image.url if image else None
```

Adapt attributes to your user model. `None` uses deterministic initials/gradient;
callback errors fall back. The enhanced widget shows initials for broken image URLs.
Guest email is not in the context. Registered names are current; guest names stay
as submitted.

## Dynamic templates

Return template-name strings such as `articles/discussion.html` from
`GET_COMMENT_TEMPLATES(page, request)`. The actual template still needs the widget
tag; the callback does not enable comments by itself.

## Restricted guest mail

`CAN_SEND_GUEST_EMAIL` must prove recipient access without a browser session.
Return False unless your entitlement rules authorize the recipient for this exact
target and Site. Do not use unconditional True for private content. Public Pages
need no special callback; registered non-Page objects require it for guest mail.

## CAPTCHA implementation

### Ready-to-use providers

The default remains local arithmetic, with no external requests or JavaScript
requirement. Opt into Google **reCAPTCHA v2 checkbox** (not v3/Enterprise), or
Yandex **SmartCaptcha standard widget**, in Python settings:

```python
import os

COMMENTAIL = {
    "default": {
        "CAPTCHA_BACKEND": "commentail.captcha_providers.GoogleRecaptcha",
        "CAPTCHA_OPTIONS": {
            "site_key": os.environ["CAPTCHA_SITE_KEY"],
            "secret_key": os.environ["CAPTCHA_SECRET_KEY"],
            "timeout": 3,
        },
    },
}
```

For Yandex use `commentail.captcha_providers.YandexSmartCaptcha`. Create the
matching key type with the provider and register your actual site domains.
Settings can be overridden by Site hostname as usual. `CAPTCHA_OPTIONS` is
replaced as a whole in a hostname section; provide both keys there. Never put
secret keys in templates, source control or client JavaScript.

The bundled script loads the selected provider only when a challenge is shown,
mounts independent widgets after form/reply updates, clears expired/error tokens,
and releases widgets when forms are removed. An incomplete check keeps the draft
local when enhanced JavaScript is active. External widgets have no routine Refresh
task button; Retry check appears after a loading or runtime error and preserves the
draft. Expired checks use the provider widget again. Load Commentail's JavaScript even
with ordinary HTML form submission: external widgets require it.

Both adapters verify tokens over fixed HTTPS endpoints, with a 1–10 second socket
timeout (default 3), bounded response/token size and no redirects. Google checks
boolean success and the request hostname; Yandex checks `status=ok` and the exact
request host, including non-default port. Empty/mismatched host claims fail.
Optional client-IP parameters are omitted. A provider outage never disables
verification or switches to arithmetic. Drafts remain editable during an outage.
Without JavaScript, a required external challenge prevents submission. The form
explains that the visitor must enable JavaScript in their browser, complete the
check, then send the comment. There is no arithmetic, email-only or additional
moderation-queue fallback: it would provide a weaker admission path and add mail
or moderation load. Existing adaptive remembered-email exemptions still apply;
disabling JavaScript grants no exemption. Provider tokens
are independently single-use and expire according to the provider's rules. The
local Google/Yandex challenge binding lasts `FORM_TICKET_SECONDS` (one hour by
default), so time spent writing before solving the widget does not consume a
five-minute CAPTCHA deadline. No background renewal requests are made. Arithmetic
and custom backends retain `CAPTCHA_SECONDS`.

External providers process browser data under their own terms. Configure site
privacy disclosures and CSP using the chosen provider's current documentation;
do not disable CSP. Google starts at `www.google.com`/`www.gstatic.com`, Yandex
at `smartcaptcha.cloud.yandex.ru`; allow the required script/frame/connect sources.
Automated tests use mocked responses, not real keys or external verification.

Protocols: [Google display](https://developers.google.com/recaptcha/docs/display),
[Google verification](https://developers.google.com/recaptcha/docs/verify),
[Yandex widgets](https://yandex.cloud/en/docs/smartcaptcha/concepts/widget-methods),
[Yandex verification](https://yandex.cloud/en/docs/smartcaptcha/concepts/validation).

The bundled forms issue independent challenges. Opening another tab does not
revoke an existing proof; refresh invalidates only the submitted challenge in
the same browser/Site. Direct `create_captcha(request, site)` callers retain the
legacy session-wide replacement; `replace_id=""` creates an independent task,
and an explicit `replace_id` refreshes that task. Backends themselves retain
the same `create`/`verify` signatures.

### Custom backends

Implement a no-argument backend with the documented create/verify methods. The
public template posts `answer` and preserves the hidden challenge field. Keep all
solutions and private provider state server-side. Library proof constraints wrap
custom backends; your backend cleans up its own extra state. A backend change
invalidates previously issued tasks. Arithmetic CAPTCHA alone is not strong bot detection.

---

[← Templates](Templates.md) · [Documentation home](Home.md) · [Object adapters →](Object-adapters.md)
