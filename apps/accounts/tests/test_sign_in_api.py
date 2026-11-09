"""Login, refresh, logout and /auth/me over HTTP, with the real services and nudge_test."""

import re
from datetime import timedelta

import pytest
from django.core import mail
from django.db import connection
from django.urls import URLPattern, URLResolver, get_resolver
from rest_framework.test import APIClient

from apps.accounts.tests.fakes import VALID_REGISTRATION
from common.errors import ServiceUnavailable
from common.infra.cache import DjangoCache
from common.security.argon2_password_hasher import Argon2PasswordHasher
from common.security.refresh_tokens import sha256_hex, split_refresh_value
from config import container

pytestmark = pytest.mark.django_db

API = "/api/v1/auth/"
REGISTER, VERIFY, LOGIN, REFRESH, LOGOUT, ME, CSRF = (
    f"{API}{name}/" for name in ("register", "verify", "login", "refresh", "logout", "me", "csrf")
)
EMAIL = VALID_REGISTRATION["email"]
PASSWORD = VALID_REGISTRATION["password"]
SIGN_UP = {**VALID_REGISTRATION, "type": VALID_REGISTRATION["account_type"]}
del SIGN_UP["account_type"]
COOKIE = "nudge_refresh"
AGENT = "Mozilla/5.0 (X11; Linux x86_64) Firefox/130.0"


def post(client: APIClient, url: str, data: object = None, **extra: str):
    return client.post(url, data if data is not None else {}, format="json", **extra)


def code_from_mail() -> str:
    match = re.search(r"Your code is (\d{6})\.", mail.outbox[-1].body)
    assert match
    return match.group(1)


def sessions() -> list[tuple]:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT id, refresh_token_hash, device_name, host(ip_address), revoked_at, "
            "expires_at, created_at FROM user_sessions ORDER BY created_at, id"
        )
        return cursor.fetchall()


def audit_actions() -> list[str]:
    with connection.cursor() as cursor:
        cursor.execute("SELECT action FROM audit_logs ORDER BY id")
        return [row[0] for row in cursor.fetchall()]


@pytest.fixture
def account(client, clock):
    """A registered and verified account; the sign-up client keeps its own cookie jar."""
    assert post(client, REGISTER, SIGN_UP).status_code == 202
    assert post(client, VERIFY, {"email": EMAIL, "code": code_from_mail()}).status_code == 200
    clock.advance(31)
    return client


def sign_in(remember: bool = False, **extra: str) -> tuple[APIClient, object]:
    fresh = APIClient()
    response = post(
        fresh,
        LOGIN,
        {"email": EMAIL, "password": PASSWORD, "remember": remember},
        HTTP_USER_AGENT=AGENT,
        REMOTE_ADDR="198.51.100.20",
        **extra,
    )
    return fresh, response


# ---- login


def test_login_returns_an_access_token_and_the_user(account):
    _, response = sign_in()
    body = response.json()
    assert response.status_code == 200 and set(body) == {"access", "user"}
    assert body["user"]["email"] == EMAIL and body["user"]["verified"] is True
    assert body["user"]["role"] == "owner" and body["user"]["type"] == "business"
    assert response["Cache-Control"] == "no-store"


def test_the_refresh_cookie_is_http_only_lax_scoped_and_a_session_cookie_by_default(account):
    _, response = sign_in(remember=False)
    cookie = response.cookies[COOKIE]
    assert cookie["httponly"] is True and cookie["samesite"] == "Lax"
    assert cookie["path"] == "/api/v1/auth/" and cookie["max-age"] == ""


def test_keep_me_signed_in_sets_a_thirty_day_cookie_and_session(account, clock):
    _, response = sign_in(remember=True)
    assert int(response.cookies[COOKIE]["max-age"]) == 30 * 24 * 3600
    expiries = sorted(row[5] for row in sessions())
    assert abs(expiries[-1] - (clock.now() + timedelta(days=30))) < timedelta(seconds=2)
    assert abs(expiries[0] - (clock.now() - timedelta(seconds=31) + timedelta(days=1))) < timedelta(
        seconds=2
    )


def test_the_body_never_holds_the_refresh_value_or_a_hash(account):
    _, response = sign_in()
    text = response.content.decode()
    assert response.cookies[COOKIE].value not in text
    assert "password" not in response.json()["user"] and "argon2" not in text


def test_login_stores_a_hash_the_device_the_address_and_an_audit_row(account):
    _, response = sign_in()
    value = response.cookies[COOKIE].value
    row = next(s for s in sessions() if s[1] == sha256_hex(value))
    assert split_refresh_value(value) == row[0]
    assert (row[2], row[3]) == (AGENT, "198.51.100.20")
    assert value not in str(sessions())
    assert audit_actions()[-1] == "user.login"
    with connection.cursor() as cursor:
        cursor.execute("SELECT last_login IS NOT NULL FROM users")
        assert cursor.fetchone() == (True,)


def test_wrong_password_and_unknown_email_get_the_same_401_and_no_cookie(account):
    wrong = post(APIClient(), LOGIN, {"email": EMAIL, "password": "Wrong-Password-1x"})
    unknown = post(APIClient(), LOGIN, {"email": "nobody@example.com", "password": PASSWORD})
    assert (wrong.status_code, wrong.json()) == (unknown.status_code, unknown.json())
    assert wrong.status_code == 401 and wrong.json()["code"] == "AUTH_BAD_CREDENTIALS"
    assert COOKIE not in wrong.cookies and COOKIE not in unknown.cookies
    assert audit_actions().count("user.login_failed") == 2


def test_an_unverified_account_gets_403_after_the_right_password_and_no_session(client, clock):
    post(client, REGISTER, SIGN_UP)
    clock.advance(31)
    before = len(sessions())
    response = post(client, LOGIN, {"email": EMAIL, "password": PASSWORD})
    assert (response.status_code, response.json()["code"]) == (403, "AUTH_EMAIL_UNVERIFIED")
    assert COOKIE not in response.cookies and len(sessions()) == before
    wrong = post(client, LOGIN, {"email": EMAIL, "password": "Wrong-Password-1x"})
    assert wrong.status_code == 401


def test_the_sixth_attempt_in_a_minute_is_429_with_retry_after(account):
    for _ in range(5):
        post(APIClient(), LOGIN, {"email": EMAIL, "password": "Wrong-Password-1x"})
    response = post(APIClient(), LOGIN, {"email": EMAIL, "password": PASSWORD})
    assert response.status_code == 429 and 1 <= int(response["Retry-After"]) <= 60
    assert response.json()["code"] == "COMMON_RATE_LIMITED"


def test_with_the_cache_down_login_is_refused_not_unprotected(account, monkeypatch):
    class Down:
        def __getattr__(self, name):
            raise ServiceUnavailable()

    monkeypatch.setattr(container, "cache_store", lambda: DjangoCache(Down()))
    _, response = sign_in()
    assert response.status_code == 503 and COOKIE not in response.cookies


def test_bad_fields_are_reported_together_and_unknown_fields_refused(account):
    bad = post(APIClient(), LOGIN, {"email": "nope", "password": "", "remember": "yes"})
    assert bad.status_code == 400 and set(bad.json()["fields"]) == {"email", "password", "remember"}
    extra = post(APIClient(), LOGIN, {"email": EMAIL, "password": PASSWORD, "admin": True})
    assert extra.status_code == 400 and "admin" in extra.json()["fields"]


def test_remember_is_optional(account):
    response = post(APIClient(), LOGIN, {"email": EMAIL, "password": PASSWORD})
    assert response.status_code == 200 and response.cookies[COOKIE]["max-age"] == ""


def test_login_works_with_the_real_argon2_hasher(client, clock, monkeypatch):
    monkeypatch.setattr(container, "password_hasher", lambda: Argon2PasswordHasher())
    post(client, REGISTER, SIGN_UP)
    post(client, VERIFY, {"email": EMAIL, "code": code_from_mail()})
    clock.advance(31)
    assert sign_in()[1].status_code == 200
    wrong = post(APIClient(), LOGIN, {"email": EMAIL, "password": "Wrong-Password-1x"})
    assert wrong.status_code == 401


# ---- /auth/me


def test_me_returns_the_user_for_a_valid_token(account):
    _, login = sign_in()
    reader = APIClient()
    response = reader.get(ME, HTTP_AUTHORIZATION=f"Bearer {login.json()['access']}")
    assert response.status_code == 200 and response.json() == login.json()["user"]
    assert response["Cache-Control"] == "no-store"


@pytest.mark.parametrize(
    "header",
    [None, "", "Bearer", "Bearer garbage", "Basic abc", "bearer lower.case.token"],
)
def test_me_without_a_good_token_is_401(account, header):
    extra = {} if header is None else {"HTTP_AUTHORIZATION": header}
    response = APIClient().get(ME, **extra)
    assert response.status_code == 401 and response.json()["code"] == "AUTH_ACCESS_TOKEN_INVALID"


def test_me_refuses_an_expired_token(account, clock):
    _, login = sign_in()
    clock.advance(10 * 60 + 1)
    response = APIClient().get(ME, HTTP_AUTHORIZATION=f"Bearer {login.json()['access']}")
    assert response.status_code == 401


def test_me_refuses_a_token_whose_session_was_revoked(account):
    fresh, login = sign_in()
    token = login.json()["access"]
    assert post(fresh, LOGOUT).status_code == 204
    assert APIClient().get(ME, HTTP_AUTHORIZATION=f"Bearer {token}").status_code == 401


def test_me_only_accepts_get(account):
    _, login = sign_in()
    response = post(APIClient(), ME, {}, HTTP_AUTHORIZATION=f"Bearer {login.json()['access']}")
    assert response.status_code == 405


# ---- refresh


def test_refresh_rotates_the_cookie_and_gives_a_new_access_token(account):
    fresh, login = sign_in(remember=True)
    old_cookie = login.cookies[COOKIE].value
    response = post(fresh, REFRESH)
    assert response.status_code == 200 and set(response.json()) == {"access", "user"}
    new_cookie = response.cookies[COOKIE]
    assert new_cookie.value != old_cookie and new_cookie["httponly"] is True
    assert 0 < int(new_cookie["max-age"]) <= 30 * 24 * 3600
    me = APIClient().get(ME, HTTP_AUTHORIZATION=f"Bearer {response.json()['access']}")
    assert me.status_code == 200
    assert sha256_hex(new_cookie.value) in [s[1] for s in sessions()]
    assert sha256_hex(old_cookie) not in [s[1] for s in sessions()]


def test_refresh_keeps_a_browser_session_cookie_a_session_cookie(account):
    fresh, _ = sign_in(remember=False)
    assert post(fresh, REFRESH).cookies[COOKIE]["max-age"] == ""


def test_replaying_an_old_cookie_is_401_clears_the_cookie_and_revokes_the_session(account):
    fresh, login = sign_in()
    stolen = login.cookies[COOKIE].value
    newest = post(fresh, REFRESH).cookies[COOKIE].value
    thief = APIClient()
    thief.cookies[COOKIE] = stolen
    response = post(thief, REFRESH)
    assert response.status_code == 401 and response.json()["code"] == "AUTH_SESSION_INVALID"
    assert response.cookies[COOKIE].value == "" and response.cookies[COOKIE]["max-age"] == 0
    row = next(s for s in sessions() if s[0] == split_refresh_value(newest))
    assert row[4] is not None  # revoked
    assert "session.reuse_detected" in audit_actions()
    victim = APIClient()
    victim.cookies[COOKIE] = newest
    assert post(victim, REFRESH).status_code == 401


def test_refresh_without_a_cookie_is_401_and_clears_it(account):
    response = post(APIClient(), REFRESH)
    assert (response.status_code, response.json()["code"]) == (401, "AUTH_SESSION_INVALID")
    assert response.cookies[COOKIE]["max-age"] == 0


def test_refresh_with_a_forged_cookie_is_401(account):
    forged = APIClient()
    forged.cookies[COOKIE] = "not-a-token"
    assert post(forged, REFRESH).status_code == 401


def test_refresh_after_the_session_expired_is_401(account, clock):
    fresh, _ = sign_in(remember=False)
    clock.advance(24 * 3600 + 1)
    # The database decides expiry for stored rows; move the row itself back in time.
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE user_sessions SET created_at = created_at - interval '2 days', "
            "expires_at = now() - interval '1 day'"
        )
    assert post(fresh, REFRESH).status_code == 401


# ---- logout


def test_logout_is_204_clears_the_cookie_and_revokes_only_that_session(account):
    one, login_one = sign_in()
    two, login_two = sign_in()
    response = post(one, LOGOUT)
    assert response.status_code == 204 and response.content == b""
    assert response.cookies[COOKIE]["max-age"] == 0
    rows = {s[0]: s for s in sessions()}
    assert rows[split_refresh_value(login_one.cookies[COOKIE].value)][4] is not None
    assert rows[split_refresh_value(login_two.cookies[COOKIE].value)][4] is None
    assert "user.logout" in audit_actions()
    assert post(two, REFRESH).status_code == 200


def test_logout_always_succeeds(account):
    assert post(APIClient(), LOGOUT).status_code == 204
    stray = APIClient()
    stray.cookies[COOKIE] = "garbage"
    assert post(stray, LOGOUT).status_code == 204
    fresh, _ = sign_in()
    assert post(fresh, LOGOUT).status_code == 204
    assert post(fresh, LOGOUT).status_code == 204


def test_a_stale_cookie_cannot_log_the_real_session_out(account):
    fresh, login = sign_in()
    stale = login.cookies[COOKIE].value
    post(fresh, REFRESH)
    other = APIClient()
    other.cookies[COOKIE] = stale
    post(other, LOGOUT)
    assert post(fresh, REFRESH).status_code == 200


# ---- CSRF and defaults


@pytest.mark.parametrize("url", [LOGIN, REFRESH, LOGOUT])
def test_cookie_endpoints_demand_a_csrf_token(url):
    assert post(APIClient(enforce_csrf_checks=True), url, {}).status_code == 403


def test_a_full_browser_flow_with_csrf_checks_on(account):
    strict = APIClient(enforce_csrf_checks=True)
    token = strict.get(CSRF).json()["csrf_token"]
    headers = {"HTTP_X_CSRFTOKEN": token}
    login = post(strict, LOGIN, {"email": EMAIL, "password": PASSWORD, "remember": True}, **headers)
    assert login.status_code == 200
    assert post(strict, REFRESH, **headers).status_code == 200
    assert post(strict, LOGOUT, **headers).status_code == 204


def public_view_names() -> set[str]:
    return {
        "auth-csrf",
        "auth-register",
        "auth-verify",
        "auth-resend",
        "auth-login",
        "auth-refresh",
        "auth-logout",
        "auth-reset",
        "auth-reset-confirm",
        "health",
    }


def walk(patterns, prefix=""):
    for entry in patterns:
        if isinstance(entry, URLResolver):
            yield from walk(entry.url_patterns)
        elif isinstance(entry, URLPattern) and entry.name:
            yield entry


def test_every_endpoint_is_private_unless_it_is_on_the_public_list():
    from rest_framework.permissions import IsAuthenticated

    private = []
    for entry in walk(get_resolver().url_patterns):
        view_class = getattr(entry.callback, "cls", None)
        if view_class is None or entry.name in public_view_names():
            continue
        private.append(entry.name)
        assert view_class.permission_classes == [IsAuthenticated] or IsAuthenticated in list(
            view_class.permission_classes
        ), entry.name
    assert {"auth-me", "auth-password"} <= set(private)
    for entry in walk(get_resolver().url_patterns):
        if entry.name in public_view_names():
            assert entry.callback.cls.permission_classes == [], entry.name
