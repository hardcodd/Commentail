# Install Commentail in Wagtail

## Requirements and package

| Component | Supported by 0.1.0 |
| --- | --- |
| Python | 3.12, 3.13, 3.14 |
| Wagtail | >=7.4.3,<7.5 |
| Django | >=5.2,<5.3 |
| Database | SQLite or PostgreSQL; CI covers PostgreSQL 14 |
| Frontend | Django templates, JavaScript optional |

Use a virtual environment and install the release from PyPI:

```sh
python -m pip install commentail==0.1.0
```

For the PostgreSQL driver use `python -m pip install 'commentail[postgres]==0.1.0'`.
Alternatively, install a downloaded wheel or extract the source archive and run
`python -m pip install .` in its root. Your site's `DATABASES` setting still selects
the actual database.

## 1. Apps, middleware and templates

Add `commentail` and `wagtail.contrib.settings` to your existing `INSTALLED_APPS`.
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

---

[← Home](Home.md) · [Documentation home](Home.md) · [Configuration →](Configuration.md)
