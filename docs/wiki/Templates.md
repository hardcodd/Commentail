# Template and email customization

For lists outside the discussion widget, use
[`commentail_recent` with your own markup](Recent-comments.md).

For the guarantees from 1.0.0, see the [template contract](Template-contract.md)
and [stability policy](Stability.md).

## Override paths

Put matching relative paths in your project templates directory ahead of app
loaders. Copy from the installed version, make focused edits and recheck on upgrades.

| Under commentail/ | Purpose |
| --- | --- |
| block.html | Wrapper, private/public status, root list |
| comment.html | Message, author, avatar, actions |
| replies.html | Expansion and reply list |
| form.html | Main/reply composer |
| edit-form.html | Inline editor |
| captcha.html | Arithmetic challenge |
| base.html | Email-action document layout |
| action.html | Confirmation, unsubscribe, status content |

Preserve CSRF, submission keys, target/addressee identifiers and server URLs.
Keep `data-discussion`, `data-commentail-navigation`, `.commentail-form`,
`.commentail-edit-form` and the localized `.commentail-network-error` region.
Preserve labels, status/error roles, focus targets and language attributes.
Do not cache personalized widget HTML. Test with JS and without it.

## Structured data

The default widget includes conditional Comment microdata and script-safe JSON-LD.
See [Structured data](Structured-data.md) before replacing the comment/block templates
or combining their output with a host page graph.

## Style action documents

Copy `commentail/base.html` into your project and add your stylesheet to its
existing `extra_head` block, or adapt the layout to your site's base. Preserve
content, heading and return-link blocks and the `strict-origin` referrer policy;
a global `no-referrer` meta tag can break native CSRF forms. Document-specific
styles are scoped by `.commentail-document` and the document custom properties.
Discussion/editing stay in the article; confirmation/unsubscribe are action screens.

## Mail templates and public context

Place overrides in your project templates directory, ahead of Commentail in
Django's template loader order. For each kind (`confirm`, `edit`, `published`,
`rejected`, `reply`), the stable paths are:

- `commentail/emails/<kind>_subject.txt`: required nonempty, single-line subject
  (surrounding whitespace is stripped).
- `commentail/emails/<kind>.txt`: required plain-text body.
- `commentail/emails/<kind>.html`: HTML alternative, included since 0.2.0
  (published 0.1.1 has plain text only).

The default emails use a neutral card, the host Site name, one primary link
styled as a button, descriptive secondary links and a copyable action URL. Both
alternatives explain confirmation, editing, moderation and per-comment unsubscribe.
Revision decisions have distinct subjects and body text. There are no remote
images, fonts or tracking assets. Existing per-kind host overrides still win.

The new `commentail/emails/base.html` and `button.html` are shared presentation
helpers, not additions to the stable context or per-kind path contract. Override
all five HTML bodies if you need fully independent markup. Keep plain-text and
HTML copy/actions consistent when overriding either. An empty per-kind HTML
override produces an empty HTML part; it does not disable multipart mail.

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

---

[← Styling](Styling.md) · [Documentation home](Home.md) · [Callbacks →](Callbacks.md)
