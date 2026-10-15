"""Development-only example settings; not a production deployment template."""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
RUNTIME_DIR = BASE_DIR / ".runtime"
RUNTIME_DIR.mkdir(exist_ok=True)
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "local-commentail-example-only")
DEBUG = True
ALLOWED_HOSTS = ["127.0.0.1", "localhost", "testserver"]
SESSION_COOKIE_NAME = "commentail_example_session"
CSRF_COOKIE_NAME = "commentail_example_csrf"
CSRF_FAILURE_VIEW = "commentail.public.csrf_failure"
INSTALLED_APPS = [
    "demo_home",
    "commentail",
    "wagtail.contrib.settings",
    "wagtail",
    "wagtail.users",
    "wagtail.images",
    "wagtail.documents",
    "wagtail.snippets",
    "wagtail.admin",
    "wagtail.search",
    "wagtail.sites",
    "modelcluster",
    "taggit",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.environ.get(
            "COMMENTAIL_EXAMPLE_DB", str(RUNTIME_DIR / "db.sqlite3")
        ),
    }
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
USE_TZ = True
LANGUAGE_CODE = "en"
STATIC_URL = "/static/"
ROOT_URLCONF = "demo.urls"
MIDDLEWARE = [
    "commentail.middleware.CapabilityHeadersMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = os.environ.get("EMAIL_HOST", "")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "1025"))
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = os.environ.get("EMAIL_USE_TLS", "0") == "1"
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "comments@example.invalid")
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ]
        },
    }
]
WAGTAILADMIN_BASE_URL = "http://127.0.0.1:8000"
WAGTAIL_SITE_NAME = "Commentail example"
MEDIA_ROOT = RUNTIME_DIR / "media"
MEDIA_URL = "/media/"
STATIC_ROOT = RUNTIME_DIR / "static"
COMMENTAIL = {
    "default": {
        "OBJECT_ADAPTERS": {"demo_home.Product": "demo_home.comments.ProductAdapter"}
    }
}
LANGUAGES = [("en", "English"), ("ru", "Russian")]
