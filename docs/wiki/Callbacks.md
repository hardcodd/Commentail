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

Implement a no-argument backend with the documented create/verify methods. The
public template posts `answer` and preserves the hidden challenge field. Keep all
solutions and private provider state server-side. Library proof constraints wrap
custom backends; your backend cleans up its own extra state. A backend change
invalidates previously issued tasks. Arithmetic CAPTCHA alone is not strong bot detection.

---

[← Templates](Templates.md) · [Documentation home](Home.md) · [Object adapters →](Object-adapters.md)
