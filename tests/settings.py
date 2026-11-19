"""Settings for the tests and the demo site (python demo.py)."""

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

SECRET_KEY = "not-secret-tests-only"
DEBUG = True
ALLOWED_HOSTS = ["*"]

INSTALLED_APPS = [
    # Before wagtail.admin: it adds the translation row to the page editor.
    "wagtail_sidebyside",
    "tests.testapp",
    "wagtail.contrib.settings",
    "wagtail.contrib.typed_table_block",
    "wagtail.locales",
    "wagtail.embeds",
    "wagtail.sites",
    "wagtail.users",
    "wagtail.snippets",
    "wagtail.documents",
    "wagtail.images",
    "wagtail.search",
    "wagtail.admin",
    "wagtail",
    "modelcluster",
    "taggit",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]

ROOT_URLCONF = "tests.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
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

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "demo.sqlite3",
    }
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LANGUAGE_CODE = "fr"
LANGUAGES = [("fr", "Français"), ("en", "English")]
WAGTAIL_CONTENT_LANGUAGES = LANGUAGES
WAGTAIL_I18N_ENABLED = True
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
MEDIA_ROOT = BASE_DIR / "media"
MEDIA_URL = "/media/"

WAGTAIL_SITE_NAME = "Side-by-side demo"
WAGTAILADMIN_BASE_URL = "http://localhost:8000"

SIDEBYSIDE = {
    "SOURCE_LOCALE": "fr",
    "AI_PROVIDER": "",
}
