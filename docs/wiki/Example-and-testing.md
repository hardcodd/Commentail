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

GitHub Actions runs the contract suite for Python 3.12, 3.13 and 3.14
with SQLite and PostgreSQL 14, plus
JavaScript, lint, migrations, translations and the source/wheel distributions.
`requirements-test.txt` pins the acceptance environment; it is not a host-site
production lockfile. Install it before running the checks below.

```sh
python -m django test tests --settings=tests.settings
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
`commentail_synthetic_tests`; never use a production cluster.

Checks cover transitions and concurrent writers, CSRF/admission, Site permissions,
author-only visibility, guest confirmation/editing, mail claims, template detection,
registered-object access/isolation/cleanup and Page create/edit saving. CI also builds
a wheel from the source distribution, tests that installed wheel outside the checkout,
and checks the included example through migrations, bootstrap, worker and static collection.

The minimum supported Wagtail patch is 7.4.3. Earlier 7.4 patches are excluded
because of upstream security fixes; the test pin and installed environments use
7.4.3. See the [Wagtail 7.4.3 release notes](https://docs.wagtail.org/en/stable/releases/7.4.3.html).

## Acceptance boundaries

The current suite includes 229 server tests and 31 JS tests. CI runs six
Python 3.12–3.14 × file SQLite/PostgreSQL 14 combinations, quality and distributions.
See [GitHub Actions](https://github.com/hardcodd/Commentail/actions/workflows/tests.yml).
Installed Safari, Chrome, Yandex and Firefox were exercised with/without JS, including
CSV, guest mail and inline interactions. Selected Safari VoiceOver scenarios and a
physical phone were checked. Previous major browser versions remain unverified;
this is not exhaustive device coverage or accessibility certification. Host-specific
customizations and deployment policies need their own acceptance checks.

---

[← Troubleshooting](Troubleshooting.md) · [Documentation home](Home.md) · [Release 0.1.0 →](Release-0.1.0.md)
