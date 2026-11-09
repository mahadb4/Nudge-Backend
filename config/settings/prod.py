"""Production and staging. Every value that matters must come from the environment."""

from .base import *  # noqa: F403
from .base import CACHES, EMAIL_HASH_KEY, JWT_SIGNING_KEY, SECRET_KEY, env
from .checks import assert_shared_cache, assert_strong_keys

DEBUG = False
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS")

assert_strong_keys(
    {"SECRET_KEY": SECRET_KEY, "JWT_SIGNING_KEY": JWT_SIGNING_KEY, "EMAIL_HASH_KEY": EMAIL_HASH_KEY}
)
assert_shared_cache(CACHES)

SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=True)
SECURE_HSTS_SECONDS = 63_072_000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = False
# Preload puts the domain on the browsers' built-in HTTPS-only list. Removal takes months, so it is
# a
# permanent commitment for the domain and all subdomains. It is decided at deployment, not here.
# Silencing the matching --deploy warning keeps that check clean until then.
SILENCED_SYSTEM_CHECKS = ["security.W021"]
CSRF_COOKIE_SECURE = True
REFRESH_COOKIE_SECURE = True
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_DOMAIN = env("CSRF_COOKIE_DOMAIN", default=None)
