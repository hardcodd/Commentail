<div align="center">

# Commentail

**Self-hosted comments for Wagtail CMS**

Moderated discussions, verified guests and inline replies — styled by your site.

[![Tests and distributions](https://github.com/hardcodd/Commentail/actions/workflows/tests.yml/badge.svg?branch=main)](https://github.com/hardcodd/Commentail/actions/workflows/tests.yml)
[![Django Packages · Commentail](https://img.shields.io/badge/Django%20Packages-Commentail-0C4B33.svg)](https://djangopackages.org/packages/p/commentail/)

English · [Русский](README.ru.md)

[Get started](#quick-start) · [Documentation](https://github.com/hardcodd/Commentail/blob/main/docs/wiki/Home.md) · [Wiki](https://github.com/hardcodd/Commentail/wiki) · [Support](#support-commentail)

<img src="https://raw.githubusercontent.com/hardcodd/Commentail/main/docs/assets/commentail-preview.png" alt="Commentail — a blue bird perched on a comment bubble" width="100%">

</div>

Commentail is a Django comments library for **Wagtail 7.4 LTS and 8.0**. Add a
Django template tag to an article, moderate discussions inside Wagtail, and keep
content, accounts and email delivery in your own application.

The widget inherits your site's typography and colors. CSS custom properties,
replaceable templates and Python callbacks let you adapt it without a frontend
framework or an external comments platform.

> **0.2.0 Beta** adds recent comments, six languages,
> HTML emails and indexed database reads.
> [Version-to-version changelog](https://github.com/hardcodd/Commentail/blob/main/CHANGELOG.md) · [Roadmap](https://github.com/hardcodd/Commentail/blob/main/docs/wiki/Roadmap.md).
> [Changes and upgrade notes](https://github.com/hardcodd/Commentail/blob/main/docs/releases/0.2.0.md).

## Why Commentail?

| For readers | For editors | For developers |
| --- | --- | --- |
| Guest email verification or existing site accounts | Four moderation policies | One template tag for Pages and registered objects |
| Inline replies and author editing | Site defaults and Page overrides | CSS properties and template overrides |
| Direct-reply email with unsubscribe | Word/phrase rules and CSV import/export | Replaceable avatars, names and CAPTCHA |
| Responsive layout and plain HTML fallbacks | Site-scoped group permissions | Database outbox; no Redis/Celery requirement |

Comments are plain text with an adjustable 5000-character default. Optional
clickable HTTP(S) links use safe attributes. Replies can address any visible
message while keeping one visual nesting level. Moderators approve, reject,
hide, restore or erase text; they never rewrite another author's words.

Published comments include **Schema.org Comment microdata and JSON-LD**, using
the visible text and author name. Choose either format or disable output in Python.
[Structured-data guide →](https://github.com/hardcodd/Commentail/blob/main/docs/wiki/Structured-data.md)

## Compatibility

| Component | Version / requirement |
| --- | --- |
| Python | 3.12–3.14 |
| Wagtail / Django | 7.4.3+ in 7.4 / Django 5.2 or 6.0; 8.0.x / Django 5.2, 6.0 or 6.1 |
| Database | File SQLite or PostgreSQL 16 |
| UI and email languages | English, Russian, German, French, Spanish and Brazilian Portuguese |
| Frontend | Django templates, optional progressive JavaScript |
| License | [MIT](https://github.com/hardcodd/Commentail/blob/main/LICENSE) |

This table describes the 0.2.0 Beta release. CI defines all five framework
pairs on Python 3.12, 3.13 and 3.14 with both databases (30 combinations).
Package bounds are `Wagtail>=7.4.3,<8.1` and `Django>=5.2,<6.2`; only the pairs
listed above are supported. Wagtail 7.4 with Django 6.1 is outside this matrix.
Wagtail 8.1 and later require separate verification before support is declared.

Guest comments require configured SMTP and the scheduled worker. Registered
users can comment without an email address, but receive no mail. Your site
provides login and registration. No required external CDN or CAPTCHA service.

### Languages

Alongside English and Russian, 0.2.0 includes German (`de`), French (`fr`),
Spanish (`es`) and Brazilian Portuguese (`pt-br`) for the public UI,
moderation/settings and all notification emails.
The host site selects the active Django language; queued emails retain the
recipient's saved language. User comments and rejection reasons are not translated.
Documentation remains in English and Russian.
[Language configuration →](docs/wiki/Configuration.md#languages)

## Quick start

### 1. Install

In your site's virtual environment, install the release:

```sh
python -m pip install commentail==0.2.0
```

For the optional PostgreSQL driver, use
`python -m pip install 'commentail[postgres]==0.2.0'`.
You can also extract the source distribution and run `python -m pip install .` in its root.
When upgrading from 0.1.1, review the
[upgrade notes](https://github.com/hardcodd/Commentail/blob/main/docs/releases/0.2.0.md),
including migration `0014_reading_indexes` and email overrides. For older
installations, also review the [0.1.1 notes](docs/releases/0.1.1.md). The 0.1.0 package retains
its original Wagtail 7.4 and Django 5.2 limits.

### 2. Connect Django and Wagtail

- Add `commentail` and `wagtail.contrib.settings` to your existing `INSTALLED_APPS`.
- With PostgreSQL, also include `django.contrib.postgres` (required by Django 6.x checks).
- Insert `commentail.middleware.CapabilityHeadersMiddleware` before CSRF middleware.
- Retain the host session/authentication/messages middleware and template request context processor.
- Include Commentail URLs **before** Wagtail's catch-all:

```python
path("commentail/", include("commentail.urls")),
```

Run `python manage.py migrate`, `python manage.py check` and your normal static
collection. See the [complete installation guide](https://github.com/hardcodd/Commentail/blob/main/docs/wiki/Installation.md)
for settings, URL imports, CSRF draft recovery and deployment details.

### 3. Add the widget

```django
{% load commentail_tags %}
{% commentail_css %}
{% commentail_js %}
{% commentail page %}
```

Put the resource tags once in the base template and the widget in the article.
The template controls where Page comments are available; the corresponding Page
editor receives a Comments tab. Configure site defaults, then inherit or override
on individual Pages. **Review all** is the initial moderation policy.

### Recent comments elsewhere

Use the recent-comments tag on a home page, sidebar or another template:

```django
{% load commentail_tags %}
{% commentail_recent limit=5 as recent_comments %}
{% for comment in recent_comments %}
  <a href="{{ comment.url }}">{{ comment.author_name }}: {{ comment.text|truncatechars:120 }}</a>
{% endfor %}
```

Use `page=page` for one Page and `include_replies=False` for roots only. The list
respects the current visitor's access and Site, requires a request context and
must not be shared-cached. It needs no widget CSS or JavaScript.
[Fields, filters and caching →](docs/wiki/Recent-comments.md)

### 4. Enable email and cleanup

Version 0.2.0 includes minimal HTML emails with the site name, clear action
links and equivalent plain text. Existing host email overrides take precedence.

Configure Django's SMTP settings and schedule this once per minute:

```sh
python manage.py process_commentail
```

It sends the database outbox and removes expired transient records. Guests confirm
email before moderation. Public submissions with an email are automatically
subscribed to direct-reply notifications when mail is enabled; each reply email
includes per-comment unsubscribe. [Email setup and behavior →](https://github.com/hardcodd/Commentail/blob/main/docs/wiki/Email-and-worker.md)

## Make it yours

The widget has a transparent surface and inherits the container's font and text
color, following your site's light/dark theme. Load overrides after its stylesheet:

```css
.commentail {
  --commentail-color-accent: var(--brand-link, #245a86);
  --commentail-border-radius: .5rem;
  --commentail-max-width: 100%;
}
```

Use `GET_AVATAR` to return a profile image URL, or return `None` for generated
initials. Register ordinary Django models through `OBJECT_ADAPTERS`. Technical
settings use a single `COMMENTAIL` dictionary with `default` and hostname overrides.

## Documentation by task

The [Wiki](https://github.com/hardcodd/Commentail/wiki) and the [versioned guides](https://github.com/hardcodd/Commentail/blob/main/docs/wiki/Home.md)
cover the same topics. Start with the task you need:

| Area | Guides |
| --- | --- |
| Connect | [Installation](https://github.com/hardcodd/Commentail/blob/main/docs/wiki/Installation.md) · [Runnable example](https://github.com/hardcodd/Commentail/blob/main/example/README.md) |
| Configure | [Site, Page and Python settings](https://github.com/hardcodd/Commentail/blob/main/docs/wiki/Configuration.md) · [Moderation](https://github.com/hardcodd/Commentail/blob/main/docs/wiki/Moderation.md) · [CSV rules](https://github.com/hardcodd/Commentail/blob/main/docs/wiki/Rules-and-CSV.md) |
| Reader behavior | [Guests](https://github.com/hardcodd/Commentail/blob/main/docs/wiki/Guest-comments.md) · [Replies and editing](https://github.com/hardcodd/Commentail/blob/main/docs/wiki/Replies-and-editing.md) |
| Customize | [CSS and themes](https://github.com/hardcodd/Commentail/blob/main/docs/wiki/Styling.md) · [Templates and email](https://github.com/hardcodd/Commentail/blob/main/docs/wiki/Templates.md) · [Python callbacks](https://github.com/hardcodd/Commentail/blob/main/docs/wiki/Callbacks.md) · [Django model adapters](https://github.com/hardcodd/Commentail/blob/main/docs/wiki/Object-adapters.md) |
| Operate | [SMTP and worker](https://github.com/hardcodd/Commentail/blob/main/docs/wiki/Email-and-worker.md) · [Deployment](https://github.com/hardcodd/Commentail/blob/main/docs/wiki/Deployment.md) · [Security and privacy](https://github.com/hardcodd/Commentail/blob/main/docs/wiki/Security-and-privacy.md) |
| Diagnose | [Troubleshooting / FAQ](https://github.com/hardcodd/Commentail/blob/main/docs/wiki/Troubleshooting.md) · [Example and testing](https://github.com/hardcodd/Commentail/blob/main/docs/wiki/Example-and-testing.md) · [Performance and load checks](https://github.com/hardcodd/Commentail/blob/main/docs/wiki/Performance.md) |

## Release scope and verification

[0.2.0 Beta release notes](https://github.com/hardcodd/Commentail/blob/main/docs/releases/0.2.0.md) describe the changes and upgrade steps;
[0.1.0 release notes](https://github.com/hardcodd/Commentail/blob/main/docs/releases/0.1.0.md) preserve the initial release contract.
The source distribution includes the runnable Wagtail example, tests and
guides; the wheel includes the runtime, translations, templates and static assets.

The CI workflow defines 30 framework/Python/database combinations, JavaScript, lint, migration drift,
translations and source/wheel installation. Browser checks covered installed Safari,
Chrome, Yandex Browser and Firefox with and without JS, plus selected VoiceOver
scenarios and a phone. Previous major browser versions remain unverified; this is
not an exhaustive accessibility or device certification.

There is no separate REST API, rich-text editor, uploads, likes, reports or live
updates in 0.2.0. SMTP retries can duplicate mail after an uncertain delivery result.
Host-specific themes, access rules and email delivery need their own acceptance checks.

## Support Commentail

If Commentail helps your project, you can support maintenance, documentation and
compatibility work. Contributions are optional.

**[Support via CloudTips](https://pay.cloudtips.ru/p/f92ee349)**

<a href="https://pay.cloudtips.ru/p/f92ee349"><img src="https://raw.githubusercontent.com/hardcodd/Commentail/main/docs/assets/support-qr.png" alt="Scan to support Commentail via CloudTips" width="180"></a>

For questions and reproducible bugs, check the [FAQ](https://github.com/hardcodd/Commentail/blob/main/docs/wiki/Troubleshooting.md)
then open a [GitHub issue](https://github.com/hardcodd/Commentail/issues). Do not
include credentials, private comments or protected email links.
