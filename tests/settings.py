SECRET_KEY = "synthetic-tests-only"
INSTALLED_APPS = [
    "commentail",
    "tests.targets.apps.TargetsConfig",
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
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
USE_TZ = True
LANGUAGE_CODE = "en"
STATIC_URL = "/static/"
ROOT_URLCONF = "tests.urls"
MIDDLEWARE = [
    "commentail.middleware.CapabilityHeadersMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [__import__("pathlib").Path(__file__).parent / "templates"],
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
WAGTAILADMIN_BASE_URL = "http://testserver"

# Opt into a disposable file database for real SQLite writer-concurrency tests.
import os

if os.environ.get("COMMENTAIL_TEST_SQLITE"):
    DATABASES["default"]["TEST"] = {"NAME": os.environ["COMMENTAIL_TEST_SQLITE"]}
DATABASES["default"]["OPTIONS"] = {"timeout": 20}

if os.environ.get("COMMENTAIL_TEST_POSTGRES") == "1":
    INSTALLED_APPS.append("django.contrib.postgres")
    DATABASES["default"] = {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": "postgres",
        "USER": os.environ["PGUSER"],
        "PASSWORD": os.environ["PGPASSWORD"],
        "HOST": os.environ.get("PGHOST", "127.0.0.1"),
        "PORT": os.environ.get("PGPORT", "55432"),
        "TEST": {
            "NAME": os.environ.get(
                "COMMENTAIL_TEST_DB_NAME", "commentail_synthetic_tests"
            )
        },
    }

WAGTAIL_SITE_NAME = "Commentail test"
TIME_ZONE = "UTC"
