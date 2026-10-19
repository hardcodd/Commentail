# Recent comments in your own markup

Available in the current source; not included in published 0.1.1.

Use `commentail_recent` for a sidebar, home page or another list outside the
discussion widget. It returns presentation dictionaries for your template and
requires no Commentail CSS or JavaScript.

```django
{% load commentail_tags %}
{% commentail_recent limit=5 as recent_comments %}

<ul>
  {% for comment in recent_comments %}
    <li>
      <a href="{{ comment.url }}">
        {{ comment.author_name }}: {{ comment.text|truncatechars:120 }}
      </a>
      — {{ comment.target_title }}
      <time datetime="{{ comment.published_at|date:'c' }}">
        {{ comment.published_at|date:'SHORT_DATETIME_FORMAT' }}
      </time>
    </li>
  {% empty %}
    <li>No comments yet.</li>
  {% endfor %}
</ul>
```

## Filters and ordering

| Argument | Default | Behavior |
| --- | --- | --- |
| `limit` | `5` | Nonnegative integer; `0` returns an empty list |
| `page` | Omitted | Exact saved Wagtail Page; does not include descendants |
| `include_replies` | `True` | `False` selects only root comments |

```django
{% commentail_recent limit=3 page=page include_replies=False as recent_comments %}
```

Arguments may also be template variables. Use integers and booleans, rather than
strings such as `limit="5"` or `include_replies="False"`. Invalid limit/boolean
values raise `TemplateSyntaxError`. An invalid or unsaved Page returns no rows.

Without `page`, the selection includes Wagtail Pages and registered Django objects
on the request's current Wagtail Site. With `page`, it includes only that Page.
Comments are sorted by publication time, newest first, with descending comment ID
breaking ties. The limit counts accessible results, after visibility checks;
inaccessible recent comments do not displace older accessible ones.

Only published comments with a non-null publication time at or before the current
time are eligible. Pending, rejected, hidden and deleted messages are excluded,
including the visitor's own pending messages. Read-only discussions remain eligible;
effective hidden discussions do not. Replies to hidden/deleted roots remain eligible
when the replies themselves are published, as in the standard discussion widget.

## Returned fields

Each dictionary contains exactly these fields:

| Field | Value |
| --- | --- |
| `id` | Integer comment ID |
| `author_name` | Current display name, including the existing `GET_AUTHOR_NAME` hook |
| `text` | Published plain text, without generated links or HTML |
| `published_at` | Publication datetime |
| `target_title` | Page title, or `str(obj)` for an adapted object |
| `url` | Comment permalink, including navigation to a reply outside the first batch |

No email, moderation reason, tokens, user, discussion or target model is returned.
Keep Django autoescaping enabled; do not apply `safe` to comment text or names.
Truncation, dates, empty-state wording and HTML belong to your template.

## Access, caching and integration

The context must contain `request`, normally supplied by Django's request context
processor. Without a request or a resolved Wagtail Site the tag returns an empty
list. Selection does not create discussions, forms or guest proofs.

Page comments require a live Page within the Site root, the current visitor's
access (including inherited restrictions), and a template containing the regular
`{% commentail page %}` widget. The recent-comments tag alone does not enable a
Page discussion. Object comments use the registered adapter's current Site and
`can_view` checks; unavailable targets and adapter access failures are excluded.
The existing permalink fallback applies if an object's URL adapter fails.

Results depend on the visitor. Keep `CapabilityHeadersMiddleware` installed as
described in [Installation](Installation.md); rendering this tag marks the response
`Cache-Control: private, no-store`. Do not put the list in a shared template-fragment
cache or override these headers with a public page/CDN cache.

The selector reads bounded SQL batches and reuses each discussion's access decision
and URL within one selection. Page types and ordinary restrictions are loaded in
batches. It may inspect more than `limit` candidates to fill the list, so many
inaccessible discussions can make a global selection expensive. It does not cache
permissions across requests. There is no popularity ranking or polling. See
[Performance](Performance.md) for indexes, query costs and reproducible load checks.

---

[Documentation home](Home.md) · [Templates](Templates.md) · [Object adapters](Object-adapters.md)
