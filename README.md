<div align="center">

# Commentail

**Self-hosted comments for Wagtail CMS**

Moderated discussions, verified guests and inline replies — styled by your site.

**Current release: [1.3.2](https://github.com/hardcodd/Commentail/releases/tag/v1.3.2)** · [PyPI](https://pypi.org/project/commentail/1.3.2/)

[1.3.2 restores discussions under translated Site homepages](docs/releases/1.3.2.md).
There is no new migration over 1.3.1. Upgrading from 1.3.0 or earlier includes
the [irreversible 1.3.1 fingerprint migration](docs/releases/1.3.1.md);
review its backup, downtime and form-quota guidance first.

[![Tests and distributions](https://github.com/hardcodd/Commentail/actions/workflows/tests.yml/badge.svg?branch=main)](https://github.com/hardcodd/Commentail/actions/workflows/tests.yml)
[![Django Packages · Commentail](https://img.shields.io/badge/Django%20Packages-Commentail-0C4B33.svg)](https://djangopackages.org/packages/p/commentail/)

English · [Русский](README.ru.md)

[Get started](#quick-start) · [Course](https://hardcodd.net/en/blog/?series=commentail-tutorials) · [Screenshots](#screenshots) · [Documentation](https://github.com/hardcodd/Commentail/blob/main/docs/wiki/Home.md) · [Wiki](https://github.com/hardcodd/Commentail/wiki) · [Support](#support-commentail)

<img src="https://raw.githubusercontent.com/hardcodd/Commentail/main/docs/assets/commentail-preview.png" alt="Commentail — a blue bird perched on a comment bubble" width="100%">

</div>

Commentail is a Django comments library for **Wagtail 7.4 LTS and 8.0**. Add a
Django template tag to an article, moderate discussions inside Wagtail, and keep
content, accounts and email delivery in your own application.

The widget inherits your site's typography and colors. CSS custom properties,
replaceable templates and Python callbacks let you adapt it without a frontend
framework or an external comments platform.

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

Documented integrations follow the [stable API and compatibility policy](docs/wiki/Stability.md).

## Screenshots

Captured from Commentail **1.1.0**, installed from PyPI in an isolated Wagtail
8.0.1 / Django 6.1.2 demo. Names and conversations are sample data.
The public page uses a custom host theme; the widget and admin screens are the
released package, without template overrides.

**On the site:** a discussion about Wagtail, Django templates and progressive
enhancement, with a threaded reply and a highlighted editor.

![Commentail discussion on a Wagtail article, with a reader question and an editor reply](https://raw.githubusercontent.com/hardcodd/Commentail/main/docs/assets/screenshots/public-discussion.jpg)

**Inside Wagtail:** the moderation queue, expanded site/page, status and date
filters, and two comments selected for bulk actions.

![Wagtail moderation queue with expanded filters and bulk comment selection](https://raw.githubusercontent.com/hardcodd/Commentail/main/docs/assets/screenshots/moderation-filters.jpg)

<details>
<summary>Guest form, inline reply, comment review and site/page settings</summary>

**Guest form.** A private email field, email-verification notice and the local
arithmetic challenge. The sample is an unsent draft.

![Guest comment form with a sample draft and email-verification notice](https://raw.githubusercontent.com/hardcodd/Commentail/main/docs/assets/screenshots/guest-form.jpg)

**Inline reply.** The reply form opens below the selected comment and keeps the
recipient visible. This sample is also an unsent draft.

![Inline reply form addressed to a reader, beside the existing discussion](https://raw.githubusercontent.com/hardcodd/Commentail/main/docs/assets/screenshots/inline-reply.jpg)

**Comment review.** Read the original text, choose a moderation action and inspect
its activity history.

![Individual comment awaiting moderation with available actions and activity history](https://raw.githubusercontent.com/hardcodd/Commentail/main/docs/assets/screenshots/comment-moderation.jpg)

**Site settings.** Discussion access, moderation policy, staff highlighting,
clickable links and email preferences in one place.

![Site comment settings in Wagtail, including moderation, appearance and email options](https://raw.githubusercontent.com/hardcodd/Commentail/main/docs/assets/screenshots/site-settings.jpg)

**Page settings.** Inherit the site policy or override it for an individual
discussion.

![Page discussion settings showing inheritance from the site configuration](https://raw.githubusercontent.com/hardcodd/Commentail/main/docs/assets/screenshots/page-settings.jpg)

</details>

## Compatibility

| Component | Version / requirement |
| --- | --- |
| Python | 3.12–3.14 |
| Wagtail / Django | 7.4.3+ in 7.4 / Django 5.2 or 6.0; 8.0.x / Django 5.2, 6.0 or 6.1 |
| Database | File SQLite or PostgreSQL 16 |
| UI and email languages | English, Russian, German, French, Spanish and Brazilian Portuguese |
| Frontend | Django templates, optional progressive JavaScript |
| License | [MIT](https://github.com/hardcodd/Commentail/blob/main/LICENSE) |

CI defines all five framework pairs on Python 3.12, 3.13 and 3.14 with both databases (30 combinations).
Package bounds are `Wagtail>=7.4.3,<8.1` and `Django>=5.2,<6.2`; only the pairs
listed above are supported. Wagtail 7.4 with Django 6.1 is outside this matrix.
Wagtail 8.1 and later require separate verification before support is declared.

The Wagtail 8 CI stacks select 8.0.1 or a newer patch within 8.0.

Guest comments require configured Django email delivery and scheduled background
processing. Use SMTP or another Django `EMAIL_BACKEND`, and schedule the command
or `commentail.background.process_pending()` through your existing task queue.
Registered users can comment without an email address, but receive no mail. Your
site provides login and registration. No required external CDN or CAPTCHA service.
See [email setup](docs/wiki/Email-and-worker.md).

Guest spam protection includes invisible form checks, attempt limits and review
signals for repeated long text and multiple links, including guest edits. Google
reCAPTCHA v2 and Yandex SmartCaptcha are optional adapters; external widgets
require JavaScript, with no alternative path when a check is required.
See [setup and custom providers](docs/wiki/Callbacks.md#ready-to-use-providers)
and [guest protection](docs/wiki/Security-and-privacy.md#low-friction-guest-checks).

### Languages

English (`en`), Russian (`ru`), German (`de`), French (`fr`), Spanish (`es`)
and Brazilian Portuguese (`pt-br`) are available for the public UI,
moderation/settings and all notification emails.
The host site selects the active Django language; queued emails retain the
recipient's saved language. User comments and rejection reasons are not translated.
The guides are in English; this README is also [available in Russian](README.ru.md).
[Language configuration →](docs/wiki/Configuration.md#languages)

## Quick start

### 1. Install

In your existing Wagtail site's virtual environment, install the published release:

```sh
python -m pip install commentail==1.3.2
```

For the optional PostgreSQL driver, use
`python -m pip install 'commentail[postgres]==1.3.2'`.
For an existing installation, follow
the [upgrade guide](docs/wiki/Installation.md#upgrading-and-restoring) for your target version.

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

### 4. Enable email and cleanup

Configure Django's email backend and run this command once per minute:

```sh
python manage.py process_commentail
```

The command sends queued mail and removes expired temporary records. Guests confirm
their email before moderation. Authors with email are subscribed to direct-reply
notifications when mail is enabled; every reply email includes per-comment unsubscribe.

You can configure an API-based Django backend and schedule
`commentail.background.process_pending()` in your project's queue instead of a
separate command job. Choose one schedule. Backend acceptance does not prove inbox
delivery. [Backend setup, scheduling and verification →](docs/wiki/Email-and-worker.md)

### 5. Check the integration

Submit a comment while signed in, approve it in **Comments**, then try a reply
and an eligible edit. In a separate browser session, submit as a guest and complete
email confirmation. Check the real site's theme, permissions and mail delivery.
[Deployment checks →](docs/wiki/Deployment.md#host-acceptance)

## Recent comments elsewhere

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

## Make it yours

The widget has a transparent surface and inherits the container's font and text
color, following your site's light/dark theme. No custom properties are required
for the default appearance. To customize it, load overrides after its stylesheet:

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

The [22-lesson Commentail course](https://hardcodd.net/en/blog/?series=commentail-tutorials)
walks through installation, email delivery, CAPTCHA, customization and production setup
with step-by-step examples.

The [Wiki](https://github.com/hardcodd/Commentail/wiki) and the [versioned guides](https://github.com/hardcodd/Commentail/blob/main/docs/wiki/Home.md)
cover the same topics. Start with the task you need:

| Area | Guides |
| --- | --- |
| Connect | [Installation](https://github.com/hardcodd/Commentail/blob/main/docs/wiki/Installation.md) · [Runnable example](https://github.com/hardcodd/Commentail/blob/main/example/README.md) |
| Configure | [Site, Page and Python settings](https://github.com/hardcodd/Commentail/blob/main/docs/wiki/Configuration.md) · [Moderation](https://github.com/hardcodd/Commentail/blob/main/docs/wiki/Moderation.md) · [CSV rules](https://github.com/hardcodd/Commentail/blob/main/docs/wiki/Rules-and-CSV.md) |
| Reader behavior | [Guests](https://github.com/hardcodd/Commentail/blob/main/docs/wiki/Guest-comments.md) · [Replies and editing](https://github.com/hardcodd/Commentail/blob/main/docs/wiki/Replies-and-editing.md) |
| Customize | [CSS and themes](https://github.com/hardcodd/Commentail/blob/main/docs/wiki/Styling.md) · [Templates and email](https://github.com/hardcodd/Commentail/blob/main/docs/wiki/Templates.md) · [Python callbacks](https://github.com/hardcodd/Commentail/blob/main/docs/wiki/Callbacks.md) · [Django model adapters](https://github.com/hardcodd/Commentail/blob/main/docs/wiki/Object-adapters.md) |
| Operate | [Email and background processing](https://github.com/hardcodd/Commentail/blob/main/docs/wiki/Email-and-worker.md) · [Deployment](https://github.com/hardcodd/Commentail/blob/main/docs/wiki/Deployment.md) · [Security and privacy](https://github.com/hardcodd/Commentail/blob/main/docs/wiki/Security-and-privacy.md) |
| Diagnose | [Troubleshooting / FAQ](https://github.com/hardcodd/Commentail/blob/main/docs/wiki/Troubleshooting.md) · [Example and testing](https://github.com/hardcodd/Commentail/blob/main/docs/wiki/Example-and-testing.md) · [Performance and load checks](https://github.com/hardcodd/Commentail/blob/main/docs/wiki/Performance.md) |

## Verification and limits

See the [changelog](CHANGELOG.md) and [release/upgrade guides](docs/wiki/Installation.md#upgrading-and-restoring)
for version-specific changes.
The source distribution includes the runnable Wagtail example, tests and
guides; the wheel includes the runtime, translations, templates and static assets.

The CI workflow defines 30 framework/Python/database combinations, JavaScript, lint, migration drift,
translations and source/wheel installation. Local checks and hosted CI are separate;
inspect the workflow for the revision you use. Browser/accessibility coverage and
its limits are documented in [Example and testing](docs/wiki/Example-and-testing.md#acceptance-boundaries).

There is no separate REST API, rich-text editor, uploads, likes, reports or live
updates. Mail retries can duplicate delivery after an uncertain backend result.
Host-specific themes, access rules and email delivery need their own acceptance checks.

## Support Commentail

If Commentail helps your project, you can support maintenance, documentation and
compatibility work. Contributions are optional.

**[Support via CloudTips](https://pay.cloudtips.ru/p/f92ee349)**

<a href="https://pay.cloudtips.ru/p/f92ee349"><img src="https://raw.githubusercontent.com/hardcodd/Commentail/main/docs/assets/support-qr.png" alt="Scan to support Commentail via CloudTips" width="180"></a>

For questions and reproducible bugs, check the [FAQ](https://github.com/hardcodd/Commentail/blob/main/docs/wiki/Troubleshooting.md)
then open a [GitHub issue](https://github.com/hardcodd/Commentail/issues). Do not
include credentials, private comments or protected email links.
