<div align="center">

# Commentail

**Self-hosted comments for Wagtail CMS**

Moderated discussions, verified guests and inline replies — styled by your site.

[![Tests and distributions](https://github.com/hardcodd/Commentail/actions/workflows/tests.yml/badge.svg?branch=main)](https://github.com/hardcodd/Commentail/actions/workflows/tests.yml)

[Get started](#quick-start) · [Documentation](https://github.com/hardcodd/Commentail/blob/main/docs/wiki/Home.md) · [Wiki](https://github.com/hardcodd/Commentail/wiki) · [Support](#support-commentail)

<img src="https://raw.githubusercontent.com/hardcodd/Commentail/main/docs/assets/commentail-preview.png" alt="Commentail — a blue bird perched on a comment bubble" width="100%">

</div>

Commentail is a Django comments library built for **Wagtail 7.4 LTS**. Add a
Django template tag to an article, moderate discussions inside Wagtail, and keep
content, accounts and email delivery in your own application.

The widget inherits your site's typography and colors. CSS custom properties,
replaceable templates and Python callbacks let you adapt it without a frontend
framework or an external comments platform.

> **0.1.0 is prepared for release; PyPI publication is pending.** Install the
> supplied wheel or source archive for now. Wagtail 8.0 is not supported by 0.1.0.

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

## Compatibility

| Component | Version / requirement |
| --- | --- |
| Python | 3.12–3.14 |
| Wagtail | >=7.4.3, <7.5 |
| Django | >=5.2, <5.3 |
| Database | SQLite or PostgreSQL; CI covers PostgreSQL 14 |
| UI languages | English and Russian |
| Frontend | Django templates, optional progressive JavaScript |
| License | [MIT](https://github.com/hardcodd/Commentail/blob/main/LICENSE) |

Guest comments require configured SMTP and the scheduled worker. Registered
users can comment without an email address, but receive no mail. Your site
provides login and registration. No required external CDN or CAPTCHA service.

## Quick start

### 1. Install

In your site's virtual environment, install the prepared wheel:

```sh
python -m pip install /path/to/commentail-0.1.0-py3-none-any.whl
```

Or extract the source distribution and run `python -m pip install .` in its root.
For the optional PostgreSQL driver, use `python -m pip install '.[postgres]'` from source.

### 2. Connect Django and Wagtail

- Add `commentail` and `wagtail.contrib.settings` to your existing `INSTALLED_APPS`.
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

### 4. Enable email and cleanup

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
| Diagnose | [Troubleshooting / FAQ](https://github.com/hardcodd/Commentail/blob/main/docs/wiki/Troubleshooting.md) · [Example and testing](https://github.com/hardcodd/Commentail/blob/main/docs/wiki/Example-and-testing.md) |

## Release scope and verification

[0.1.0 release notes](https://github.com/hardcodd/Commentail/blob/main/docs/releases/0.1.0.md) describe the initial feature set and
limits. The source distribution includes the runnable Wagtail example, tests and
guides; the wheel includes the runtime, translations, templates and static assets.

CI checks six Python/database combinations, JavaScript, lint, migration drift,
translations and source/wheel installation. Browser checks covered installed Safari,
Chrome, Yandex Browser and Firefox with and without JS, plus selected VoiceOver
scenarios and a phone. Previous major browser versions remain unverified; this is
not an exhaustive accessibility or device certification.

There is no separate REST API, rich-text editor, uploads, likes, reports or live
updates in 0.1.0. SMTP retries can duplicate mail after an uncertain delivery result.
Host-specific themes, access rules and email delivery need their own acceptance checks.

## Support Commentail

If Commentail helps your project, you can support maintenance, documentation and
compatibility work. Contributions are optional.

**[Support via CloudTips](https://pay.cloudtips.ru/p/f92ee349)**

<a href="https://pay.cloudtips.ru/p/f92ee349"><img src="https://raw.githubusercontent.com/hardcodd/Commentail/main/docs/assets/support-qr.png" alt="Scan to support Commentail via CloudTips" width="180"></a>

For questions and reproducible bugs, check the [FAQ](https://github.com/hardcodd/Commentail/blob/main/docs/wiki/Troubleshooting.md)
then open a [GitHub issue](https://github.com/hardcodd/Commentail/issues). Do not
include credentials, private comments or protected email links.
