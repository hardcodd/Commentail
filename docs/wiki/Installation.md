# Install Commentail in Wagtail

## Requirements and package

| Component | 1.3.1 Stable |
| --- | --- |
| Python | 3.12, 3.13, 3.14 |
| Wagtail / Django | 7.4.3+ in 7.4 / Django 5.2 or 6.0; 8.0.x / Django 5.2, 6.0 or 6.1 |
| Database | File SQLite or PostgreSQL 16 |
| Frontend | Django templates; JavaScript required for optional Google/Yandex CAPTCHA |

CI defines all five framework pairs on each listed Python version and both
databases. Package bounds are `Wagtail>=7.4.3,<8.1` and `Django>=5.2,<6.2`;
Wagtail 7.4 with Django 6.1 is not supported. Wagtail 8.1+ requires separate
verification. The published 0.1.0 artifact retains its original bounds:
`Wagtail>=7.4.3,<7.5` and `Django>=5.2,<5.3`.

In a virtual environment, install the release from PyPI:

```sh
python -m pip install commentail==1.3.1
```

For the PostgreSQL driver use
`python -m pip install 'commentail[postgres]==1.3.1'`.
Alternatively, install a downloaded wheel or extract the source archive and run
`python -m pip install .` in its root. Your site's `DATABASES` setting still selects
the actual database.
For downloaded release archives, verify the supplied checksum before installation.
See [1.3.1 changes and upgrade notes](Release-1.3.1.md) and the
[version-to-version changelog](Changelog.md).

The Wagtail 8 CI stacks now select 8.0.1 or a newer patch within 8.0; the
supported framework pairs and package bounds above are unchanged.

## 1. Apps, middleware and templates

Add `commentail` and `wagtail.contrib.settings` to your existing `INSTALLED_APPS`.
When using PostgreSQL, also include `django.contrib.postgres`; Django 6.x checks
require it for the PostgreSQL fields and indexes used by Wagtail search.
Do not duplicate an already installed app. Retain sessions, authentication, messages
and CSRF middleware. Place `commentail.middleware.CapabilityHeadersMiddleware`
before `django.middleware.csrf.CsrfViewMiddleware`. Keep
`django.template.context_processors.request` in the Django template backend.

Optionally set `CSRF_FAILURE_VIEW = "commentail.public.csrf_failure"` to preserve
rejected Commentail drafts for explicit resubmission. It does not accept a failed
POST or weaken CSRF for other views.

## 2. URLs

```python
from django.urls import include, path
from wagtail import urls as wagtail_urls

urlpatterns = [
    # Keep your existing admin, document and other application routes.
    path("commentail/", include("commentail.urls")),
    path("", include(wagtail_urls)),  # Catch-all must remain last.
]
```

## 3. Database and assets

If the site runs behind nginx, explicitly configure Commentail's
[`TRUSTED_PROXIES`](Deployment.md#client-ip-behind-nginx) before opening it to
visitors. The guide includes a local nginx example and explains how to prevent
forwarded-IP spoofing. Otherwise visitors can share the proxy's IP quotas.

```sh
python manage.py migrate
python manage.py check
python manage.py collectstatic --noinput
```

Serve collected static files through your deployment's normal static-file setup.

## 4. Connect the widget

```django
{% load commentail_tags %}
{% commentail_css %}
{% commentail_js %}
{% commentail page %}
```

Put resource tags once in the base template and the widget in the article template.
Load the tag library in each template using it. Resource tags alone do not enable
comments. A Page template containing the widget enables the Comments tab in its
editor; no Page mixin or field declaration is required. Dynamic template dependencies
use [GET_COMMENT_TEMPLATES](Callbacks.md).

## 5. Policies, accounts and worker

Choose the correct Wagtail Site and configure its Commentail settings. **Review all**
is the initial policy. Page overrides save with the standard page action and apply
immediately, independently of revision publication. Commentail uses your site's
existing accounts and supplies no login/registration system.

Configure [email delivery and once-per-minute background processing](Email-and-worker.md).
Use the host task queue or a separate command schedule. SMTP and other Django
email backends are supported. Without configured delivery, registered authors can comment
but guests cannot. Submit and approve a test
message before opening the integration to visitors.

## Upgrading and restoring

Review the notes for your target version and every intervening release:

| Target | Main upgrade considerations |
| --- | --- |
| [1.3.1](Release-1.3.1.md) | Irreversible data migration `0018`: stop writers, keep the same key and back up database/key/package. Review form overrides and shared-network issuance quotas. |
| [1.3.0](Release-1.3.0.md) | Migrations `0016`/`0017`, refreshed assets and reviewed form/provider overrides. New guest checks are review signals; external CAPTCHA is opt-in. |
| [1.2.0](Release-1.2.0.md) | No new Commentail migration over 1.1.0. Refresh assets and review form/CAPTCHA overrides; choose one background schedule. |
| [1.1.0](Release-1.1.0.md) | Migration `0015` adds staff highlighting; review author/admin overrides and publication-notice behavior. |
| [1.0.0](Release-1.0.0.md) | Stable API policy; no runtime or schema changes over 0.2.0. |
| [0.2.0](Release-0.2.0.md) | Index migration `0014` can block writes and needs extra space; review HTML/plain-text email overrides and languages. |
| [0.1.1](Release-0.1.1.md) | Framework support, URL prefixes and the 40-grapheme guest-name limit. |

For every upgrade, run `migrate`, `check` and `collectstatic --noinput`, refresh
cached assets and restart application/background processes through your normal
deployment procedure. Framework upgrades can require their own migrations.

For sites behind nginx, also review
[`TRUSTED_PROXIES` and forwarded-header handling](Deployment.md#client-ip-behind-nginx),
including existing installations that have never configured them. Verify distinct
client IPs through the real proxy before resuming traffic; shared proxy quotas
can otherwise throttle visitors together, including new form/recovery tickets.

Rehearse the upgrade on a restored copy of your site's database before changing
the live installation. Keep the previous package and exact dependency versions,
host settings, template overrides, media and secrets in a protected backup. Retain
the same `SECRET_KEY`: existing Commentail action links are derived from it as well
as their database records. A database copy alone is not a complete site backup.

For the final backup and cutover, pause site writes and the Commentail worker.
Use your database's consistent backup mechanism. For SQLite, use the
[SQLite backup API](https://docs.python.org/3.12/library/sqlite3.html#sqlite3.Connection.backup)
or an equivalent supported tool rather than copying a live database file in
isolation. For PostgreSQL, a custom-format `pg_dump -Fc` archive can be restored
into a separate empty database with
[`pg_restore --exit-on-error --single-transaction`](https://www.postgresql.org/docs/16/app-pgrestore.html).
Preserve required database roles separately; a database dump does not include
cluster-wide roles or tablespaces.

Install the reviewed target package in the rehearsal environment, then run
`migrate`, `check` and `collectstatic`. Verify existing comments/replies, pending
revisions, settings, template overrides, permissions, guest links and queued mail.
Keep rehearsal mail local. Check the actual installed package path so a source
checkout cannot silently replace the wheel under test.

Test restoration of both the pre-upgrade backup with the previous package and a
post-upgrade backup with the target package. Compare data and test new writes;
an archive that has not been restored is insufficient evidence. Replacing only
the wheel is not a general rollback procedure when a release changes the schema.
Restoring an older backup also discards later database changes. Its pending mail
may already have been sent after that snapshot; inspect the queue before resuming
the worker and account for possible duplicates. Link deadlines remain unchanged.

---

[← Home](Home.md) · [Documentation home](Home.md) · [Configuration →](Configuration.md)
