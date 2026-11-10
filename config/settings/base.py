"""Settings shared by every environment. Values that differ per machine come from the environment
(.env)."""

import os
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()
# NUDGE_ENV_FILE lets a test point at another (or no) env file; normally it is .env.
environ.Env.read_env(os.environ.get("NUDGE_ENV_FILE", BASE_DIR / ".env"), overwrite=False)

SECRET_KEY = env("SECRET_KEY")
JWT_SIGNING_KEY = env("JWT_SIGNING_KEY")
EMAIL_HASH_KEY = env("EMAIL_HASH_KEY")
DEBUG = env.bool("DEBUG", default=False)
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=[])

# No admin, sessions or messages (Q-7). auth and contenttypes stay installed so DRF and
# drf-spectacular
# import cleanly; their tables are never created because migrate is never run on the nudge database.
# Whether contrib.auth stays is decided in the step 5 design.
INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "rest_framework",
    "corsheaders",
    "drf_spectacular",
    "common",
    "apps.accounts",
    "apps.crm",
    "apps.audit",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "common.middleware.NoStoreApiMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# Needed only by the drf-spectacular Swagger UI page.
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": ["django.template.context_processors.request"]},
    }
]

STATEMENT_TIMEOUT_MS = 10_000


def database(url_variable: str) -> dict:
    """PostgreSQL settings from a URL variable. Persistent connections now; psycopg-pool at the
    production step."""
    config = env.db(url_variable)
    config["CONN_MAX_AGE"] = 60
    config["CONN_HEALTH_CHECKS"] = True
    # Every query has a timeout (CODING_STYLE 7): the server cancels anything slower than
    # STATEMENT_TIMEOUT_MS.
    config["OPTIONS"] = {
        "connect_timeout": 5,
        "application_name": "nudge-api",
        "options": f"-c statement_timeout={STATEMENT_TIMEOUT_MS}",
    }
    return config


# The nudge database is built from docs/nudge_schema_v3_1_no_pgvector.sql. migrate is never run
# (Q-7).
DATABASES = {"default": database("DATABASE_URL")}
# The name of the real development database. Commands that may only touch it (seed_demo) compare
# the connected database with this.
DEV_DATABASE_NAME = DATABASES["default"]["NAME"]

# locmemcache:// in dev (one process only); redis://host:6379/0 in staging and production.
CACHES = {"default": env.cache("CACHE_URL", default="locmemcache://")}

# Email comes from separate environment variables. Development defaults to the console backend;
# real delivery happens only when EMAIL_BACKEND names the SMTP backend. The password is never
# logged, printed or put in a message.
EMAIL_BACKEND = env("EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend")
EMAIL_HOST = env("EMAIL_HOST", default="localhost")
EMAIL_PORT = env.int("EMAIL_PORT", default=25)
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=False)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
EMAIL_TIMEOUT = env.int("EMAIL_TIMEOUT", default=10)  # seconds; every external call has one
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="Nudge <no-reply@localhost>")

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = False
USE_TZ = True

FRONTEND_URL = env("FRONTEND_URL", default="http://localhost:5173")
CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=[FRONTEND_URL])
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_HEADERS = ["authorization", "content-type", "x-csrftoken", "x-organization-id"]
CORS_EXPOSE_HEADERS = ["retry-after", "x-ratelimit-limit", "x-ratelimit-remaining"]
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[FRONTEND_URL])

# Proxies whose X-Forwarded-For may be trusted for the client IP (validation spec).
TRUSTED_PROXIES = env.list("TRUSTED_PROXIES", default=[])

# The refresh cookie is Secure outside local development (production sets it to True).
REFRESH_COOKIE_SECURE = env.bool("REFRESH_COOKIE_SECURE", default=False)

PASSWORD_HASHERS = ["django.contrib.auth.hashers.Argon2PasswordHasher"]

DATA_UPLOAD_MAX_MEMORY_SIZE = 1_000_000
FILE_UPLOAD_MAX_MEMORY_SIZE = 1_000_000

SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
X_FRAME_OPTIONS = "DENY"
CSRF_FAILURE_VIEW = "common.responses.json_csrf_failure"

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    # Secure by default: an API class is private unless it sets both lists to [] itself.
    "DEFAULT_AUTHENTICATION_CLASSES": ["config.authentication.AccessTokenAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "UNAUTHENTICATED_USER": None,
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "common.responses.exception_handler",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Nudge API",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", default="INFO")},
}
