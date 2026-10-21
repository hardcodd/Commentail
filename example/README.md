# Commentail example

A local project showing Page and non-Page integration, inherited settings and the
progressive comment widget on the [supported Wagtail/Django pairs](../docs/wiki/Installation.md).
Python 3.12–3.14 is supported. Installation below selects compatible framework
versions; use explicit framework constraints to exercise another supported pair.

From this directory, create and activate a virtual environment, then run:

```sh
python -m pip install -e ..
python manage.py migrate
python manage.py bootstrap_demo
python manage.py createsuperuser
python manage.py runserver 127.0.0.1:8000
```

Open http://127.0.0.1:8000/ and http://127.0.0.1:8000/admin/. Sign in to admin
before testing registered-user comments. Comments await moderation by default.
The page editor shows Commentail settings because the template contains the tag.
`bootstrap_demo` also prints a `/products/<id>/` URL for an ordinary Django model.
Its adapter is in `demo_home/comments.py`, registered in `demo/settings.py`.
Open the product once, then use Comments → Object discussions to edit its
inherited settings. Add `?nojs=1` to the product URL to inspect the ordinary HTML
form without loading the enhancement script.
Run `bootstrap_demo` only on this example's local database; reruns preserve the
created home and current settings. Runtime data stays in `.runtime/`.

The example defaults to SMTP. Before testing guests with a real mail server, set
`EMAIL_HOST`, `EMAIL_PORT`, optional `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`,
`DEFAULT_FROM_EMAIL` and either `EMAIL_USE_TLS=1` (STARTTLS, usually port 587)
or `EMAIL_USE_SSL=1` (implicit TLS, usually port 465) for your test mail system.
Do not enable both. No email is sent automatically by starting the example. Run the worker once per minute:

```sh
python manage.py process_commentail
```

The worker delivers queued messages and expires old proof records. Guest email
confirmation requires an explicit action in the opened link. SMTP configuration
is read from the environment; the example never writes credentials to source.
Without mail configuration, registered users can comment and guest submission is unavailable.

You can instead change
`EMAIL_BACKEND` in `demo/settings.py` to
`"django.core.mail.backends.console.EmailBackend"`. SMTP variables are then
unnecessary: the worker prints each queued email in its terminal, where you can
copy its action link and continue confirmation. This does not send to an inbox;
keep those protected links private. For real API delivery or a host task queue,
follow the [email/backend guide](../docs/wiki/Email-and-worker.md).

This project uses development settings and is not a production deployment template.
