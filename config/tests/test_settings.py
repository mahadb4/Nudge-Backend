"""Step 0 checks: the test settings load, and the settings follow the decisions in docs/."""

import os
import subprocess
import sys

import pytest
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from config.settings.checks import assert_shared_cache, assert_strong_keys

LOCMEM = "django.core.cache.backends.locmem.LocMemCache"
REDIS = "django.core.cache.backends.redis.RedisCache"


def test_settings_load():
    assert settings.SETTINGS_MODULE == "config.settings.test"
    assert settings.DEBUG is False
    assert settings.USE_TZ is True
    assert settings.TIME_ZONE == "UTC"


def test_no_admin_sessions_or_messages():
    for app in ("django.contrib.admin", "django.contrib.sessions", "django.contrib.messages"):
        assert app not in settings.INSTALLED_APPS


def test_midterm_modules_installed():
    for module in ("apps.accounts", "apps.crm", "apps.audit"):
        assert module in settings.INSTALLED_APPS


def test_json_only_api():
    assert settings.REST_FRAMEWORK["DEFAULT_RENDERER_CLASSES"] == [
        "rest_framework.renderers.JSONRenderer"
    ]
    assert settings.REST_FRAMEWORK["DEFAULT_PARSER_CLASSES"] == [
        "rest_framework.parsers.JSONParser"
    ]


def test_argon2_is_the_password_hasher():
    assert settings.PASSWORD_HASHERS[0] == "django.contrib.auth.hashers.Argon2PasswordHasher"


def test_body_limit_is_one_megabyte():
    assert settings.DATA_UPLOAD_MAX_MEMORY_SIZE == 1_000_000


def test_cors_allows_only_the_frontend_with_credentials():
    assert settings.CORS_ALLOW_CREDENTIALS is True
    assert "*" not in settings.CORS_ALLOWED_ORIGINS
    assert "x-organization-id" in settings.CORS_ALLOW_HEADERS


def test_prod_refuses_a_per_process_cache():
    with pytest.raises(ImproperlyConfigured):
        assert_shared_cache({"default": {"BACKEND": LOCMEM}})


def test_prod_accepts_redis():
    assert_shared_cache({"default": {"BACKEND": REDIS, "LOCATION": "redis://localhost:6379/0"}})


STRONG = "k" * 64
KEY_NAMES = ("SECRET_KEY", "JWT_SIGNING_KEY", "EMAIL_HASH_KEY")


def test_the_test_keys_are_fixed_distinct_and_at_least_64_bytes():
    keys = [getattr(settings, name) for name in KEY_NAMES]
    assert all(len(key.encode()) >= 64 for key in keys)
    assert len(set(keys)) == 3


def test_a_64_byte_key_is_accepted():
    assert_strong_keys({name: STRONG for name in KEY_NAMES})


@pytest.mark.parametrize("value", ["", "short", "k" * 63, "change-me-" + "k" * 80])
def test_a_weak_key_is_refused_and_only_its_name_is_reported(value):
    with pytest.raises(ImproperlyConfigured) as info:
        assert_strong_keys({"SECRET_KEY": STRONG, "JWT_SIGNING_KEY": value})
    assert "JWT_SIGNING_KEY" in str(info.value) and "SECRET_KEY" not in str(info.value)
    assert value not in str(info.value) or value == ""


def test_key_length_is_counted_in_bytes_not_characters():
    with pytest.raises(ImproperlyConfigured):
        assert_strong_keys({"SECRET_KEY": "é" * 31})  # 31 characters, 62 bytes
    assert_strong_keys({"SECRET_KEY": "é" * 32})  # 64 bytes


def test_every_weak_key_is_named_at_once():
    with pytest.raises(ImproperlyConfigured) as info:
        assert_strong_keys({"SECRET_KEY": "a", "JWT_SIGNING_KEY": "b", "EMAIL_HASH_KEY": STRONG})
    assert "JWT_SIGNING_KEY, SECRET_KEY" in str(info.value)


def test_the_development_settings_refuse_to_start_with_a_weak_key():
    weak = "weak-value-that-must-never-be-printed"
    env = {**os.environ, "DJANGO_SETTINGS_MODULE": "config.settings.dev", "JWT_SIGNING_KEY": weak}
    result = subprocess.run(
        [sys.executable, "manage.py", "check"],
        cwd=settings.BASE_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode != 0
    assert "JWT_SIGNING_KEY" in result.stderr and weak not in result.stderr + result.stdout
