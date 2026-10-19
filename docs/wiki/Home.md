# Commentail documentation

**Self-hosted comments for Wagtail CMS.** Add moderated discussions to Wagtail
Pages and registered Django models using your site's accounts, templates and styles.

> **0.2.0 Beta:** Wagtail 7.4.3+ / Django 5.2 or 6.0; Wagtail 8.0 / Django 5.2, 6.0 or 6.1; Python 3.12–3.14; file SQLite and PostgreSQL 16.
> Published 0.1.0 retains Wagtail >=7.4.3,<7.5 and Django 5.2 support.

## Find your guide

| Your task | Guide |
| --- | --- |
| Connect a Wagtail site | [Installation](Installation.md) |
| Choose site/page behavior and Python options | [Configuration](Configuration.md) |
| Review messages and delegate access | [Moderation](Moderation.md) |
| Maintain word rules in bulk | [Rules and CSV](Rules-and-CSV.md) |
| Understand guest verification | [Guest comments](Guest-comments.md) |
| Understand threads and edit restrictions | [Replies and editing](Replies-and-editing.md) |
| Deliver email and schedule cleanup | [Email and worker](Email-and-worker.md) |
| Match the host theme | [Styling](Styling.md) |
| Replace markup and email layouts | [Templates](Templates.md) |
| Show recent comments with custom markup | [Recent comments](Recent-comments.md) |
| Describe published comments to search engines | [Structured data](Structured-data.md) |
| Supply avatars, names or CAPTCHA | [Callbacks](Callbacks.md) |
| Add comments to other Django models | [Object adapters](Object-adapters.md) |
| Understand access and stored data | [Security and privacy](Security-and-privacy.md) |
| Prepare a deployment | [Deployment](Deployment.md) |
| Understand query costs and run load checks | [Performance](Performance.md) |
| Diagnose a problem | [Troubleshooting](Troubleshooting.md) |
| Run the example and tests | [Example and testing](Example-and-testing.md) |
| Read the current release scope | [Release 0.2.0](Release-0.2.0.md) |
| Compare versions | [Changelog](Changelog.md) |
| See planned work | [Roadmap](Roadmap.md) |
| Read the initial release scope | [Release 0.1.0](Release-0.1.0.md) |
| Support development | [Support](Support.md) |

## Recommended first run

1. Complete Installation on a test site.
2. Start with **Review all**, the default moderation policy.
3. Configure SMTP and schedule the worker before enabling guests.
4. Exercise publication, a reply and an eligible edit.
5. Adapt the theme and assign site-scoped moderator rights.

Plain text, server-rendered HTML and progressive JavaScript keep integration
independent of a frontend framework. Version 0.2.0 includes English, Russian,
German, French, Spanish and Brazilian Portuguese across the UI, moderation and
emails; see [Languages](Configuration.md#languages).
No external comments platform, Redis, Celery or CDN is required.

---

[Documentation home](Home.md) · [Installation →](Installation.md)
