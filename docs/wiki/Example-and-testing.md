# Runnable example and development checks

The source distribution includes `example/`, with Page and ordinary Django model
integrations. It creates no predefined admin. Create and activate a Python
3.12–3.14 virtual environment first, then use its disposable database:

```sh
cd example
python -m pip install -e ..
python manage.py migrate
python manage.py bootstrap_demo
python manage.py createsuperuser
python manage.py runserver 127.0.0.1:8000
```

Open http://127.0.0.1:8000/ and /admin/. Bootstrap also prints a product URL.
Runtime data lives in `example/.runtime/`. Read the
[example README](https://github.com/hardcodd/Commentail/blob/main/example/README.md)
for its mail configuration.
Do not run bootstrap against a production database.

## Automated checks

The GitHub Actions workflow defines 30 contract jobs: Wagtail 7.4.3+ with
Django 5.2/6.0 and Wagtail 8.0.1+ within 8.0 with Django 5.2/6.0/6.1, each on Python 3.12,
3.13 and 3.14 with file SQLite and PostgreSQL 16, plus
JavaScript, lint, migrations, translations and the source/wheel distributions.
`requirements-test.txt` pins the acceptance environment; it is not a host-site
production lockfile. From the source root, install the package and test pins:

```sh
python -m pip install -r requirements-test.txt -e .
python -m pip check
```

`requirements-test-common.txt` pins shared test dependencies without selecting
Django or Wagtail. To test another supported pair, use a fresh environment, for example:

```sh
python -m pip install -r requirements-test-common.txt 'Wagtail~=8.0.1' 'Django~=6.1.0' .
python -m pip check
```

Keep the framework pair within the [support matrix](Installation.md).

```sh
python -m django test tests --settings=tests.settings
python -m django makemigrations --check --dry-run --settings=tests.settings
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

## Current development verification

The 1.2.0 sources passed all 30 combinations on 22 October 2026,
using Wagtail 7.4.3/8.0.1 and Django 5.2.18/6.0.9/6.1.2 with the updated
certifi/Pillow test pins. Each run discovered 395 tests; PostgreSQL skipped one
SQLite-only plan check. All 42 JavaScript tests and the other checks above passed.
Real API delivery and a Redis/Celery host queue were exercised separately.
These local results do not replace CI for the publishing commit or host acceptance.

## Reported live-site verification: 0.2.0

On 19 October 2026, the integrating site's owner supplied a verification report
for published 0.2.0 on Django 6.1.2/Wagtail 8.0, using private Firefox sessions
and real Gmail/Yandex inboxes. It covered guest submission with CAPTCHA, email
confirmation, moderation, edits retaining the previous public text until approval,
reply notifications received after approval, and unsubscribe. Approved replies
after unsubscribe created no mail jobs; repeated unsubscribe kept delivery disabled.
Expired edit links were rejected, including while the comments were public.

All 24 reported negative cases were rejected without changes to the checked
related records: six altered-token GETs, six altered-token POSTs with valid CSRF
(404), and twelve POSTs without or with incorrect CSRF (403). Record counts and
SHA-256 digests of full serialized related records matched before and after.
This is bounded verification, not a complete security audit.

The report also covered a PyPI 0.1.0 → 0.2.0 upgrade, migration/data preservation,
independent backup restoration, host email overrides, static assets, RU/EN routes
and the scheduled worker. Host tests passed 346/350 initially; four analytics
configuration errors were followed by 30 passing affected tests with the usual
test setting. A full corrected 350-test rerun was not reported.

Two observations remain: Yandex initially classified confirmation mail as spam;
later checked messages reached the inbox after marking it as not spam. The owner
reports that Yandex advised recipients to mark legitimate mail as not spam to help
build sender reputation over time. This delivery observation is not treated as a
code defect or release blocker; future inbox placement is not guaranteed. Repeated
email confirmation showed the ordinary confirmation form, without a distinct
already-confirmed message, while preserving confirmation/subscription state.
Neither sustained deliverability nor all browser/email-client combinations were
established. These are owner-reported 0.2.0 results; they support the unchanged
runtime of 1.0.0 and are not a live-site test of an installed 1.0.0 package.

## Acceptance boundaries

[Performance](Performance.md) describes query regressions, the synthetic load
benchmark and its migration/traffic checks. Functional matrix success alone does
not establish the capacity of a deployed site.

The suite covers server contracts and JavaScript behavior. The workflow covers
the 30 combinations above, quality and distributions. Local matrix results are
separate from hosted CI status; inspect the workflow run for the revision in use.
See [GitHub Actions](https://github.com/hardcodd/Commentail/actions/workflows/tests.yml).
Installed Safari, Chrome, Yandex and Firefox were exercised with/without JS, including
CSV, guest mail and inline interactions. Selected Safari VoiceOver scenarios and a
physical phone were checked. Historical checks also covered Chrome 142 on macOS
and Windows ARM64 and Firefox 140 ESR on Windows ARM64, with and without JavaScript.
They exercised responsive layouts, pagination, replies, editing, validation and
network-error draft retention. Windows Chrome x64 ran under emulation; native
Windows x64 was not checked. Older Firefox on macOS could not complete startup
for automation. This is not exhaustive device coverage or accessibility certification. Host-specific
customizations and deployment policies need their own acceptance checks.

---

[← Troubleshooting](Troubleshooting.md) · [Documentation home](Home.md) · [Release 1.1.0 →](Release-1.1.0.md)
