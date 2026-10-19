# Runnable example and development checks

The source distribution includes example/, with Page and ordinary Django model
integrations. It creates no predefined admin. Use its disposable database:

```sh
cd example
python -m pip install -e ..
python manage.py migrate
python manage.py bootstrap_demo
python manage.py createsuperuser
python manage.py runserver 127.0.0.1:8000
```

Open http://127.0.0.1:8000/ and /admin/. Bootstrap also prints a product URL.
Runtime data lives in .runtime/. Read example/README.md for SMTP variables.
Do not run bootstrap against a production database.

## Automated checks

The GitHub Actions workflow defines 30 contract jobs: Wagtail 7.4.3+ with
Django 5.2/6.0 and Wagtail 8.0 with Django 5.2/6.0/6.1, each on Python 3.12,
3.13 and 3.14 with file SQLite and PostgreSQL 16, plus
JavaScript, lint, migrations, translations and the source/wheel distributions.
`requirements-test.txt` pins the acceptance environment; it is not a host-site
production lockfile. Install it before running the checks below.

`requirements-test-common.txt` pins shared test dependencies without selecting
Django or Wagtail. To test another supported pair, use a fresh environment, for example:

```sh
python -m pip install -r requirements-test-common.txt 'Wagtail~=8.0.0' 'Django~=6.1.0' .
python -m pip check
```

Keep the framework pair within the [support matrix](Installation.md).

```sh
python -m django test tests --settings=tests.settings
# Requires GNU gettext tools on PATH; checks every catalog against current sources:
python tools/check_translations.py
# Optional development check with Node.js (no npm dependencies):
node --test tests/test_*.js
```

Default tests use synthetic in-memory SQLite. Set `COMMENTAIL_TEST_SQLITE` to a
fresh disposable file for writer-concurrency tests. PostgreSQL checks require a
dedicated synthetic cluster/user:

```sh
COMMENTAIL_TEST_POSTGRES=1 PGUSER=commentail_test PGHOST=127.0.0.1 PGPORT=55432 \
  python -m django test tests --settings=tests.settings
```

Supply PGPASSWORD securely in the environment. The runner creates/destroys
`commentail_synthetic_tests`; set `COMMENTAIL_TEST_DB_NAME` to a unique disposable
database name for parallel runs. The PostgreSQL test settings include
`django.contrib.postgres`, as required by Django 6.x. Never use a production cluster.

Checks cover transitions and concurrent writers, CSRF/admission, Site permissions,
author-only visibility, guest confirmation/editing, mail claims, template detection,
registered-object access/isolation/cleanup and Page create/edit saving. CI also builds
a wheel from the source distribution, tests that installed wheel outside the checkout,
and checks the included example through migrations, bootstrap, worker and static collection.

The minimum supported Wagtail patch is 7.4.3. Earlier 7.4 patches are excluded
because of upstream security fixes; the test pin and installed environments use
7.4.3. See the [Wagtail 7.4.3 release notes](https://docs.wagtail.org/en/stable/releases/7.4.3.html).

## Acceptance boundaries

The suite covers server contracts and JavaScript behavior. The workflow covers
the 30 combinations above, quality and distributions. Local matrix results are
separate from hosted CI status; inspect the workflow run for the revision in use.
See [GitHub Actions](https://github.com/hardcodd/Commentail/actions/workflows/tests.yml).
Installed Safari, Chrome, Yandex and Firefox were exercised with/without JS, including
CSV, guest mail and inline interactions. Selected Safari VoiceOver scenarios and a
physical phone were checked. Previous major browser versions remain unverified;
this is not exhaustive device coverage or accessibility certification. Host-specific
customizations and deployment policies need their own acceptance checks.

---

[← Troubleshooting](Troubleshooting.md) · [Documentation home](Home.md) · [Release 0.1.1 →](Release-0.1.1.md)
