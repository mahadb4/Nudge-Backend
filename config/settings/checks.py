"""Startup checks used by the production settings. Pure functions so they can be tested without
loading prod."""

from collections.abc import Mapping

from django.core.exceptions import ImproperlyConfigured

MIN_KEY_BYTES = 64
PLACEHOLDER_PREFIX = "change-me"

SHARED_CACHE_BACKENDS = frozenset({"django.core.cache.backends.redis.RedisCache"})
# Backends that never deliver anything to a real mailbox.
NON_DELIVERY_EMAIL_BACKENDS = frozenset(
    {
        "django.core.mail.backends.console.EmailBackend",
        "django.core.mail.backends.locmem.EmailBackend",
        "django.core.mail.backends.dummy.EmailBackend",
        "django.core.mail.backends.filebased.EmailBackend",
    }
)


def assert_email_settings(backend: str, timeout: int, *, production: bool) -> None:
    """The email timeout must be positive, and production must really deliver mail.

    Only setting names are reported; no value from the environment is ever printed.
    """
    if timeout <= 0:
        raise ImproperlyConfigured("EMAIL_TIMEOUT must be a positive number of seconds.")
    if production and backend in NON_DELIVERY_EMAIL_BACKENDS:
        raise ImproperlyConfigured(
            "EMAIL_BACKEND must be a delivering backend in production "
            "(for example django.core.mail.backends.smtp.EmailBackend)."
        )


def assert_shared_cache(caches: Mapping[str, Mapping[str, object]]) -> None:
    """Rate limits and verification codes must live in a cache every process shares (Q-10)."""
    backend = caches.get("default", {}).get("BACKEND")
    if backend not in SHARED_CACHE_BACKENDS:
        raise ImproperlyConfigured(
            "CACHE_URL must point at Redis in production (got %s)." % backend
        )


def assert_strong_keys(keys: Mapping[str, str]) -> None:
    """Signing and hashing keys must be at least 64 bytes and not a copied placeholder.

    Only the names of weak keys are reported, never their values.
    """
    weak = [
        name
        for name, value in keys.items()
        if len(value.encode("utf-8")) < MIN_KEY_BYTES or value.startswith(PLACEHOLDER_PREFIX)
    ]
    if weak:
        raise ImproperlyConfigured(
            f"{', '.join(sorted(weak))}: each key must be at least {MIN_KEY_BYTES} bytes "
            "of randomness "
            '(python -c "import secrets; print(secrets.token_urlsafe(64))").'
        )
