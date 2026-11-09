"""pytest settings. Safe defaults so tests run without a .env; a real .env still wins.

Tests use their own database, nudge_test, rebuilt from the SQL files at the start of every session
by
conftest.py (common/testdb.py). It must be local and end with _test; the builder refuses anything
else.
"""

import os
from pathlib import Path

import environ

# Read .env first so its values win; the defaults below only fill what .env does not set.
environ.Env.read_env(Path(__file__).resolve().parent.parent.parent / ".env", overwrite=False)

os.environ.setdefault("SECRET_KEY", "test-only-secret-key-not-for-real-use")
os.environ.setdefault("JWT_SIGNING_KEY", "test-only-jwt-key-not-for-real-use")
os.environ.setdefault("EMAIL_HASH_KEY", "test-only-email-hash-key-not-for-real-use")
os.environ.setdefault("DATABASE_URL", "postgres://postgres@localhost:5432/nudge")
os.environ.setdefault("TEST_DATABASE_URL", "postgres://postgres@localhost:5432/nudge_test")

from .base import *  # noqa: E402, F403
from .base import BASE_DIR, database, env  # noqa: E402

# Fixed 64+ byte keys: tests never use the real keys from .env, and PyJWT has nothing to warn about.
SECRET_KEY = "test-only-secret-key-" + "0123456789abcdef" * 4
JWT_SIGNING_KEY = "test-only-jwt-signing-key-" + "fedcba9876543210" * 4
EMAIL_HASH_KEY = "test-only-email-hash-key-" + "a1b2c3d4e5f60718" * 4

DEBUG = False
ALLOWED_HOSTS = ["testserver"]
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

DATABASES = {"default": database("TEST_DATABASE_URL")}
DATABASES["default"]["CONN_MAX_AGE"] = 0

TEST_DATABASE_URL = env("TEST_DATABASE_URL")
DEV_DATABASE_NAME = env.db("DATABASE_URL")["NAME"]
NUDGE_SCHEMA_SQL = BASE_DIR / env(
    "NUDGE_SCHEMA_SQL", default="docs/nudge_schema_v3_1_no_pgvector.sql"
)
NUDGE_SEED_SQL = BASE_DIR / env("NUDGE_SEED_SQL", default="docs/nudge_seed.sql")
