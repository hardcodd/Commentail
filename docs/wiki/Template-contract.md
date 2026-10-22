# Stable template contract

**Applies from 1.0.0.** This is the explicit presentation
surface covered by [Stability](Stability.md). Use it with [Templates](Templates.md).
Translated values may be strings or Django lazy strings; exact wording is not API.

## Widget context

`commentail/block.html` always receives:

| Fields | Meaning |
| --- | --- |
| `language_code` | Active language string or None |
| `discussion_id`, `page_id` | Integer IDs; page_id is None for ordinary objects |
| `hidden` | Boolean; hidden widgets render no section |
| `entered_text`, `entered_name`, `entered_email`, `error` | Strings; text is empty during editing; error may be translated |
| `editing` | Editor mapping below, or None |
| `options` | Readable editorial settings below |

`options` exposes `mode` (`open/read_only/hidden`), `moderation`
(`all/guests/none/rules`), `access` (`all/registered/guests/none`), `max_length`
(integer), `clickable_links`, `notify_publication` and `notify_rejection` (booleans).
`highlight_staff` (boolean, from 1.1.0) controls Site-wide staff decorations.
These fields are public; the internal Python class is not.

Only when `hidden=False`, the following fields are available:

| Fields | Meaning |
| --- | --- |
| `rows`, `own` | Public root cards and current visitor's private cards |
| `count` | Published message count, including replies |
| `window_token` | Opaque root pagination window |
| `more_url`, `cancel_reply_url`, `submit_url` | Server-generated strings; more_url may be empty |
| `can_post`, `guest_email_confirmed`, `structured_microdata` | Booleans |
| `form_key`, `main_form_key` | Opaque strings; the latter is populated for an active reply |
| `form_age`, `main_form_age` | Public form-ticket IDs used only to retain server-checked draft age. |
| `captcha` | CaptchaTask or None |
| `captcha_unavailable` | Optional bool; keep the editable form and refresh control visible when challenge issuance fails. |
| `remembered_email` | Confirmed guest email string or empty string |
| `reply_to` | Published addressee card or None |
| `structured_comments` | List passed directly to commentail_json_ld; empty when disabled |

`mail_notice` is present only for a one-time translated notice. Use conditional
checks for optional fields. Django supplies `request` through its request context
processor and `csrf_token` through its normal CSRF integration. Additional host
context-processor fields do not become Commentail API.

Widget context and private cards are visitor-specific; never place them in a shared cache.

## Cards

Public/private cards expose `id` (integer), `display_name`, `initials`, `gradient`
(strings), `avatar_url` (string or None), `body` (already escaped SafeString with
permitted links/line breaks), `published_at` and `edited_at` (aware datetime or None),
`status`, `status_label`, `reason`, `resend_url`, `edit_url`, `permalink`, `reply_url`,
`reply_to_id` (integer or None), `reply_to_name` (string) and `schema` (metadata or None).
From 1.1.0, `highlight_staff` and `show_crown` are additional boolean card fields.
They already account for the Site switch and the current active author's flags.
Built-in templates share `commentail/author.html` for the name badge and
`commentail/avatar.html` for the avatar and crown, including private pending cards.
The crown sits outside the decorative, clipped avatar with an accessible label;
author text and schema metadata are unchanged. Custom author markup must render these
fields to adopt highlighting; existing overrides remain valid.

Statuses are `awaiting_email/pending/published/rejected/hidden/deleted`;
status_label is translated and must not be parsed. reason is populated only for
rejection. Optional action URLs may be empty. A reply URL alone does not authorize replying.

Root cards additionally expose `reply_count`, `opened`, `reply_window`,
`expand_url` and `more_replies`. `replies` exists only when opened=True; children
have base-card fields without recursive root additions. Private awaiting-email
cards additionally expose `delivery_message` and `confirmation_expires_at`.
A pending revision stays private; public output retains approved text.

`schema` exposes `identifier`, `url`, `target`, `author`, `text`, `published`
(strings), and `modified`/`parent` (string or None). Dates are ISO 8601. Private
cards and hidden/deleted placeholders have no schema. Do not apply `safe` to raw
user text or assemble internal schema classes yourself.

## Forms and action pages

Preserve POST actions and CSRF, hidden `key` (form_key), optional `reply_to`,
textarea `text`, guest `name`/`email`, and CAPTCHA `challenge`/`answer`.
The default guest form also has a hidden `commentail_contact` honeypot; omitting
it in older overrides remains accepted, with no honeypot signal. Preserve the
optional hidden `form_age` field for enhanced reading navigation; it is not a
submission key or a client-provided timestamp.
The refresh button submits `refresh=1` with formnovalidate. Keep the same key for
an explicit retry after network failure; do not automatically retry a POST.
The guest name field retains its documented 40-grapheme limit.

`editing` has `id`, `text`, `error`, `can_edit`, `url` and `cancel_url`. Only render
a submit form when can_edit=True. Preserve hidden `edit_comment`, textarea `text`,
CSRF and the server action. Label/required/aria-describedby and error alerts
remain part of the accessible forms. No public subscription checkbox is promised.

`commentail/base.html` exposes blocks `title`, `extra_head`, `heading`, `content`
and `return_label`. Keep the language, viewport, accessible heading and
`strict-origin` referrer policy. A global no-referrer policy can break native CSRF.
Base/action contexts always have `language_code`, `page_title`, `return_url`.
Ordinary action pages add `purpose`, `token`, `message`, `error`, `text`,
`status_label`, `reason`; only view exposes text/reason. Errors instead set
`unavailable=True`, `error`, `return_url="/"` and omit the action/token/content
fields. Confirm/unsubscribe forms remain native POST forms outside the widget;
edit redirects to the inline editor. See [mail paths and context](Templates.md#mail-templates-and-public-context).

## Progressive JavaScript hooks

| Hook | Requirement |
| --- | --- |
| `.commentail[data-discussion]`, `id="commentail"`, `lang`, `data-window` | One replaceable root for the discussion, active language and opaque pagination window |
| `data-published-label`, `data-network-error` | Localized status/error labels |
| `.commentail-network-error` | Initially hidden descendant with role=alert |
| `.commentail-error[role="alert"]`, `.commentail-header h2` | Error and fallback focus targets |
| `.commentail-comment`, `id="commentail-<id>"`, `.commentail-content` | Card, permanent anchor and target for inserted reply/editor content |
| `.commentail-pending`, `id="commentail-private-<id>"`, optional data-reply-to | Private result card and addressee |
| `.commentail-status`, first `strong` in card | Result status and author name for announcements |
| `.commentail-mail-notice` | One-time notice with role=status |
| `.commentail-replies[data-thread]`, data-open, data-window | Root ID and opened-thread window |
| `template.commentail-main-template` | First content element is a complete independent main form |
| `.commentail-editor` | Inline editor/error/cancel wrapper inside the card |
| `.commentail-avatar-image`, `textarea.commentail-input` | Broken-avatar fallback and textarea sizing |
| `input[data-commentail-name-limit]` | Guest-name limit used by progressive enhancement |
| `a[data-commentail-navigation]` | Working same-origin href, usable without JS |
| data-commentail-focus="text" | Navigation's requested field focus |
| data-commentail-reply, data-commentail-edit | Addressee/comment ID, plus navigation hook and server href |
| data-commentail-cancel, data-commentail-edit-cancel | Reply/edit cancel controls with navigation hook and server href |
| `.commentail-form[data-reply-to]`, `.commentail-edit-form[data-edit-comment]` | Active reply/editor and corresponding ID |
| `details.commentail-menu > summary` | Author menu; Escape closes and returns focus |

The script owns aria-busy, temporary tabindex/disabled state, the temporary reply
form class and the persistent `.commentail-announcement` live region before the
replaceable root. Overrides must not hard-code those transient states or move
the announcement inside the replaced fragment. Native links/forms must work when
JavaScript or enhancement APIs are absent. Main/reply/edit drafts remain separate.
Multiple copies of the same discussion widget on one page are not promised.

[Documentation home](Home.md) · [Stability](Stability.md)
