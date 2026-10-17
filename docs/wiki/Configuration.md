# Configure sites, pages and technical options

## Editorial settings in Wagtail

| Setting | Initial value | Page override |
| --- | --- | --- |
| Mode | Open | Yes |
| Moderation | Review all | Yes |
| Who can comment | Guests and registered users | Yes |
| Maximum text length | 5000 visible characters | Yes |
| Clickable links | Off | Yes |
| Publication emails | Off | Yes |
| Rejection emails | Off | Yes |
| Send emails | On | No, Site only |

Each Page/object field can **Use site setting**. Select the correct Site before
editing defaults. Policy changes do not automatically decide existing queue items.

| Mode | Existing public discussion | New comments / edits |
| --- | --- | --- |
| Open | Visible | Subject to access and policy |
| Read only | Visible | Disabled |
| Hidden | Hidden, retained | Disabled |

Moderation remains available in closed modes. Hiding defers eligible mail and does
not erase data. Target access still governs visibility; each Site has its own discussion.

## Technical settings in Python

```python
COMMENTAIL = {
    "default": {
        "AUTHOR_LIMIT_PER_HOUR": 20,
        "GET_AVATAR": "myproject.comments.get_avatar",
    },
    "www.example.org": {"AUTHOR_LIMIT_PER_HOUR": 40},
}
```

Resolution: library defaults → `default` → server-selected Wagtail `Site.hostname`.
Use the exact stored hostname, without scheme, port or path. Omitted values inherit.
Editorial fields such as `mode` do not belong in this dictionary. `OBJECT_ADAPTERS`
and `RULES_CSV_*` are project-wide and must be in `default`.

Run `python manage.py check` after changes. Unknown keys, invalid types, nonpositive
integer limits and unimportable handlers fail with `commentail.E001`. Durations
are integer seconds; callbacks are import-path strings. Existing tokens retain
their issued deadlines when a configured duration changes.

## Complete reference

| Key | Default | Meaning |
| --- | --- | --- |
| `STRUCTURED_DATA` | `"both"` | Schema.org output: `both`, `json_ld`, `microdata` or `off`; per-host overrides supported. See [Structured data](Structured-data.md). |
| `OBJECT_ADAPTERS` | `{}` | Model label → adapter class import path (project-wide). |
| `RULES_CSV_MAX_BYTES` | `5242880` | Maximum CSV upload bytes (project-wide). |
| `RULES_CSV_MAX_ROWS` | `20000` | Maximum imported rule rows (project-wide). |
| `FORM_TICKET_SECONDS` | `3600` | Private form/recovery ticket lifetime. |
| `EDIT_WINDOW_SECONDS` | `900` | Edit window from publication; accepted replies lock earlier. |
| `EMAIL_CONFIRM_SECONDS` | `86400` | Confirmation deadline from initial acceptance. |
| `GUEST_GRANT_SECONDS` | `2592000` | Browser proof lifetime from confirmation; never sliding. |
| `CAPTCHA_SECONDS` | `300` | CAPTCHA expiry. |
| `CAPTCHA_ATTEMPTS` | `5` | Attempts per challenge. |
| `AUTHOR_MIN_INTERVAL` | `30` | Minimum seconds between author submissions. |
| `AUTHOR_LIMIT_PER_HOUR` | `20` | Accepted submissions per account/email per Site/hour. |
| `IP_LIMIT_PER_HOUR` | `100` | Accepted submissions per IP per Site/hour. |
| `RESEND_MIN_INTERVAL` | `60` | Minimum seconds between confirmation resends. |
| `RESEND_LIMIT_PER_HOUR` | `5` | Resends per author/Site/hour. |
| `RESEND_IP_LIMIT_PER_HOUR` | `20` | Resends per IP/Site/hour. |
| `CAPTCHA_IP_LIMIT_PER_MINUTE` | `10` | Challenge creations per IP/Site/minute. |
| `CAPTCHA_IP_LIMIT_PER_HOUR` | `100` | Challenge creations per IP/Site/hour. |
| `TRUSTED_PROXIES` | `[]` | Trusted immediate proxy networks; [] uses the direct peer. |
| `GUEST_REQUEST_CHECKS` | `['missing_user_agent', 'cross_site']` | Supplemental guest header signals; [] disables these signals only. |
| `MAIL_RETENTION_SECONDS` | `604800` | Queued notification lifetime. |
| `MAIL_LEASE_SECONDS` | `300` | Outbox worker claim lease. |
| `MAIL_RETRY_SECONDS` | `[60, 300, 900]` | Automatic retry delay sequence in seconds. |
| `ACTION_LINK_SECONDS` | `2592000` | General action-link lifetime, not an extension of edit eligibility. |
| `CAN_SEND_GUEST_EMAIL` | `None` | Offline guest recipient access-check callback import path. |
| `GET_COMMENT_TEMPLATES` | `None` | Dynamic Page template dependency callback import path. |
| `GET_AVATAR` | `None` | Avatar callback import path. |
| `CAPTCHA_BACKEND` | `None` | Backend class import path; None selects arithmetic. |
| `GET_AUTHOR_NAME` | `None` | Current account name callback import path. |

Author/email and IP quotas apply across all Pages of a Site, with separate Site counters.
Read [Callbacks](Callbacks.md), [Email](Email-and-worker.md) and [Security](Security-and-privacy.md) before overriding their related options.

---

[← Installation](Installation.md) · [Documentation home](Home.md) · [Moderation →](Moderation.md)
