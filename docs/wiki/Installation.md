# Install Commentail in Wagtail

## Requirements and package

| Component | 0.2.0 Beta |
| --- | --- |
| Python | 3.12, 3.13, 3.14 |
| Wagtail / Django | 7.4.3+ in 7.4 / Django 5.2 or 6.0; 8.0.x / Django 5.2, 6.0 or 6.1 |
| Database | File SQLite or PostgreSQL 16 |
| Frontend | Django templates, JavaScript optional |

CI defines all five framework pairs on each listed Python version and both
databases. Package bounds are `Wagtail>=7.4.3,<8.1` and `Django>=5.2,<6.2`;
Wagtail 7.4 with Django 6.1 is not supported. Wagtail 8.1+ requires separate
verification. The published 0.1.0 artifact retains its original bounds:
`Wagtail>=7.4.3,<7.5` and `Django>=5.2,<5.3`.

In a virtual environment, install the release from PyPI:

```sh
python -m pip install commentail==0.2.0
```

For the PostgreSQL driver use
`python -m pip install 'commentail[postgres]==0.2.0'`.
Alternatively, install a downloaded wheel or extract the source archive and run
`python -m pip install .` in its root. Your site's `DATABASES` setting still selects
the actual database.
For downloaded release archives, verify the supplied checksum before installation.
See [0.2.0 changes and upgrade notes](Release-0.2.0.md) and the
[version-to-version changelog](Changelog.md).

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

Configure [SMTP and the once-per-minute worker](Email-and-worker.md). Without SMTP,
registered authors can comment but guests cannot. Submit and approve a test
message before opening the integration to visitors.

## Upgrading and restoring

Version 0.2.0 adds migration `0014_reading_indexes` over 0.1.1. It creates
publication/thread, active CAPTCHA and rate-cleanup indexes without changing
comment content or state. Standard index builds may block writes and need extra
disk space; SQLite also rebuilds the rate-event table for the field-index change.
Measure on a representative restored copy and plan a maintenance
window where appropriate. See [performance guidance](Performance.md#database-upgrade).
Recollect static files for the searchable moderation Page chooser. Review both
HTML and plain-text email overrides; existing host overrides retain precedence.
The recent-comments tag is additive and requires no changes to existing widgets.
See [0.2.0 release notes](Release-0.2.0.md). For upgrades from 0.1.0, also follow
[0.1.1 notes](Release-0.1.1.md), including guest-name validation.

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
[`pg_restore --exit-on-error --single-transaction`](https://www.postgresql.org/docs/14/app-pgrestore.html).
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
