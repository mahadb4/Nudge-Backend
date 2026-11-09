"""Local development. Runs with `python manage.py runserver` (one process, so locmemcache:// is
allowed)."""

from .base import *  # noqa: F403
from .base import EMAIL_HASH_KEY, JWT_SIGNING_KEY, SECRET_KEY, env
from .checks import assert_strong_keys

DEBUG = env.bool("DEBUG", default=True)
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])

assert_strong_keys(
    {"SECRET_KEY": SECRET_KEY, "JWT_SIGNING_KEY": JWT_SIGNING_KEY, "EMAIL_HASH_KEY": EMAIL_HASH_KEY}
)
