# Guest comments and email verification

## First submission

Guests enter a required name (up to 40 visible characters), email and plain-text
comment. Email is private and shown only in the admin. Text defaults to 5000 visible
characters, including spaces and line breaks; composed emoji count as one character.
HTML and Markdown are not rendered.

Names may include a first and last name or a nickname. Surrounding whitespace is
trimmed before counting Unicode graphemes. Longer new names are rejected without
truncation; existing saved names and registered account names are unchanged.

An unremembered guest completes a local arithmetic CAPTCHA: five-minute expiry,
five attempts, refresh available. Refresh invalidates the old challenge. This is
one spam layer, not a guarantee against automated submissions.

1. Acceptance creates a private submission and queues verification mail.
2. Opening the link displays a confirmation form; GET alone confirms nothing.
3. Pressing Confirm verifies email, then applies moderation and filtering.
4. Publication happens immediately or after a moderator's decision.
5. Publication sends a separate guest editing-link email.

The confirmation deadline is 24 hours **from acceptance**, including delivery delays.
Resends never extend it. The worker fully deletes unconfirmed submissions after expiry.

## Remembered email

Proof is remembered in the browser separately for each Site/email for 30 days
from confirmation. Matching submissions need neither new CAPTCHA nor new email
proof while it is valid. Visits and submissions do not renew the deadline.
A different browser/email, cleared storage or expired proof requires verification again.
This proof is not a registered site account.

## Private status and edits

Unpublished content is author-only, through the submitting browser/account or a
protected status link. The browser can inspect confirmation-mail status and resend
eligible mail. An email address alone never proves ownership. Guest edits open
inline from the protected publication email link and use the same rules as account
edits: see [Replies and editing](Replies-and-editing.md).

Site email and SMTP must be enabled for guest submission. Also check author access,
discussion mode, target permission and quotas. See [Email and worker](Email-and-worker.md).

---

[← Rules and CSV](Rules-and-CSV.md) · [Documentation home](Home.md) · [Replies and editing →](Replies-and-editing.md)
