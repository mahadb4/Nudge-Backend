"""Password change, forgot password and reset over HTTP, with the real services and nudge_test."""

import re

import pytest
from django.core import mail
from django.db import connection
from rest_framework.test import APIClient

from apps.accounts.tests.fakes import VALID_REGISTRATION
from common.security.argon2_password_hasher import Argon2PasswordHasher
from config import container

pytestmark = pytest.mark.django_db

API = "/api/v1/auth/"
REGISTER, VERIFY, LOGIN, REFRESH, ME, PASSWORD_URL, RESET, CONFIRM = (
    f"{API}{name}/"
    for name in (
        "register",
        "verify",
        "login",
        "refresh",
        "me",
        "password",
        "reset",
        "reset/confirm",
    )
)
EMAIL = VALID_REGISTRATION["email"]
OLD = VALID_REGISTRATION["password"]
NEW = "Copper-Meadow-Gate-55"
SIGN_UP = {**VALID_REGISTRATION, "type": VALID_REGISTRATION["account_type"]}
del SIGN_UP["account_type"]
COOKIE = "nudge_refresh"


def post(client: APIClient, url: str, data: object = None, **extra: str):
    return client.post(url, data if data is not None else {}, format="json", **extra)


def stored_password() -> str:
    with connection.cursor() as cursor:
        cursor.execute("SELECT password FROM users")
        return cursor.fetchone()[0]


def audit_actions() -> list[str]:
    with connection.cursor() as cursor:
        cursor.execute("SELECT action FROM audit_logs")
        return [row[0] for row in cursor.fetchall()]


def live_sessions() -> int:
    with connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM user_sessions WHERE revoked_at IS NULL")
        return cursor.fetchone()[0]


@pytest.fixture
def account(client, clock):
    post(client, REGISTER, SIGN_UP)
    code = re.search(r"Your code is (\d{6})\.", mail.outbox[-1].body).group(1)
    assert post(client, VERIFY, {"email": EMAIL, "code": code}).status_code == 200
    clock.advance(31)
    mail.outbox.clear()
    return client


def sign_in(password: str = OLD) -> tuple[APIClient, str]:
    fresh = APIClient()
    response = post(fresh, LOGIN, {"email": EMAIL, "password": password})
    assert response.status_code == 200, response.json()
    return fresh, response.json()["access"]


def bearer(token: str) -> dict[str, str]:
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


def link_token() -> str:
    return re.search(r"new-password\?token=([\w-]+)", mail.outbox[-1].body).group(1)


# ---- POST /auth/password/


def test_changing_the_password_is_204_and_signs_the_other_devices_out(account, clock):
    keep, keep_token = sign_in()
    clock.advance(61)
    away, away_token = sign_in()
    before = stored_password()
    response = post(keep, PASSWORD_URL, {"current": OLD, "password": NEW}, **bearer(keep_token))
    assert response.status_code == 204 and response.content == b""
    assert stored_password() != before
    assert APIClient().get(ME, **bearer(keep_token)).status_code == 200
    assert APIClient().get(ME, **bearer(away_token)).status_code == 401
    assert post(away, REFRESH).status_code == 401
    assert post(keep, REFRESH).status_code == 200
    assert "user.password_change" in audit_actions()


def test_the_new_password_works_and_the_old_one_does_not(account, clock):
    keep, token = sign_in()
    post(keep, PASSWORD_URL, {"current": OLD, "password": NEW}, **bearer(token))
    clock.advance(61)
    assert post(APIClient(), LOGIN, {"email": EMAIL, "password": OLD}).status_code == 401
    assert post(APIClient(), LOGIN, {"email": EMAIL, "password": NEW}).status_code == 200


def test_the_owner_is_told_by_email_without_the_password(account):
    keep, token = sign_in()
    post(keep, PASSWORD_URL, {"current": OLD, "password": NEW}, **bearer(token))
    notice = mail.outbox[-1]
    assert notice.to == [EMAIL] and "password was changed" in notice.body
    assert OLD not in notice.body and NEW not in notice.body


def test_a_wrong_current_password_is_a_400_on_the_current_field(account):
    keep, token = sign_in()
    before = stored_password()
    response = post(
        keep, PASSWORD_URL, {"current": "Wrong-Pass-77x", "password": NEW}, **bearer(token)
    )
    assert response.status_code == 400
    assert response.json()["fields"]["current"][0]["code"] == "AUTH_WRONG_CURRENT_PASSWORD"
    assert stored_password() == before and not mail.outbox


def test_new_password_rules_are_reported_on_the_password_field(account):
    keep, token = sign_in()
    response = post(keep, PASSWORD_URL, {"current": OLD, "password": "short"}, **bearer(token))
    assert response.status_code == 400
    assert response.json()["fields"]["password"][0]["code"] == "VALIDATION_PASSWORD_TOO_SHORT"


def test_changing_to_the_same_password_is_refused(account):
    keep, token = sign_in()
    response = post(keep, PASSWORD_URL, {"current": OLD, "password": OLD}, **bearer(token))
    assert response.json()["fields"]["password"][0]["code"] == "VALIDATION_PASSWORD_SAME_AS_CURRENT"


def test_the_sixth_try_in_a_quarter_hour_is_429(account):
    keep, token = sign_in()
    for _ in range(5):
        post(keep, PASSWORD_URL, {"current": "Wrong-Pass-77x", "password": NEW}, **bearer(token))
    response = post(keep, PASSWORD_URL, {"current": OLD, "password": NEW}, **bearer(token))
    assert response.status_code == 429 and int(response["Retry-After"]) >= 1


@pytest.mark.parametrize("header", [None, "Bearer garbage"])
def test_changing_a_password_needs_a_valid_token(account, header):
    extra = {} if header is None else {"HTTP_AUTHORIZATION": header}
    response = post(APIClient(), PASSWORD_URL, {"current": OLD, "password": NEW}, **extra)
    assert response.status_code == 401 and stored_password().startswith("fake$")
    assert stored_password() == "fake$" + OLD[::-1]


def test_unknown_fields_are_refused(account):
    keep, token = sign_in()
    response = post(
        keep, PASSWORD_URL, {"current": OLD, "password": NEW, "email": "x@y.com"}, **bearer(token)
    )
    assert response.status_code == 400 and "email" in response.json()["fields"]


# ---- POST /auth/reset/ and /auth/reset/confirm/


def test_asking_for_a_link_is_202_with_the_same_body_for_every_address(account):
    known = post(APIClient(), RESET, {"email": EMAIL})
    unknown = post(APIClient(), RESET, {"email": "nobody@example.com"})
    assert (known.status_code, known.json()) == (unknown.status_code, unknown.json())
    assert known.status_code == 202 and known.json()["code"] == "AUTH_RESET_LINK_SENT"
    assert len(mail.outbox) == 1 and mail.outbox[0].to == [EMAIL]
    assert re.search(r"/new-password\?token=[\w-]{4,200}", mail.outbox[0].body)


def test_the_reset_flow_end_to_end(account, clock):
    keep, token = sign_in()
    post(APIClient(), RESET, {"email": EMAIL})
    reset_token = link_token()
    response = post(APIClient(), CONFIRM, {"token": reset_token, "password": NEW})
    assert response.status_code == 204 and response.content == b""
    assert live_sessions() == 0
    assert APIClient().get(ME, **bearer(token)).status_code == 401
    assert post(keep, REFRESH).status_code == 401
    clock.advance(61)
    assert post(APIClient(), LOGIN, {"email": EMAIL, "password": NEW}).status_code == 200
    assert {"user.password_reset_request", "user.password_reset"} <= set(audit_actions())
    assert "password was changed" in mail.outbox[-1].body


def test_a_link_works_once(account):
    post(APIClient(), RESET, {"email": EMAIL})
    reset_token = link_token()
    assert post(APIClient(), CONFIRM, {"token": reset_token, "password": NEW}).status_code == 204
    again = post(APIClient(), CONFIRM, {"token": reset_token, "password": "Other-Gate-Pass-91"})
    assert again.status_code == 400 and again.json()["code"] == "AUTH_INVALID_TOKEN"
    assert "fields" not in again.json()


def test_an_expired_link_is_refused(account, clock):
    post(APIClient(), RESET, {"email": EMAIL})
    reset_token = link_token()
    clock.advance(3601)
    response = post(APIClient(), CONFIRM, {"token": reset_token, "password": NEW})
    assert response.json()["code"] == "AUTH_INVALID_TOKEN"


@pytest.mark.parametrize("token", ["", "x", "a" * 500, "0" * 32 + "-1-" + "0" * 64, 7, None])
def test_a_wrong_token_is_the_same_400(account, token):
    response = post(APIClient(), CONFIRM, {"token": token, "password": NEW})
    assert (response.status_code, response.json()["code"]) == (400, "AUTH_INVALID_TOKEN")


def test_a_weak_new_password_is_a_field_error_and_the_link_survives(account):
    post(APIClient(), RESET, {"email": EMAIL})
    reset_token = link_token()
    weak = post(APIClient(), CONFIRM, {"token": reset_token, "password": "short"})
    assert weak.status_code == 400 and "password" in weak.json()["fields"]
    assert post(APIClient(), CONFIRM, {"token": reset_token, "password": NEW}).status_code == 204


def test_the_sixth_request_for_a_link_in_an_hour_for_one_address_is_429(account):
    for _ in range(3):
        assert post(APIClient(), RESET, {"email": EMAIL}).status_code == 202
    response = post(APIClient(), RESET, {"email": EMAIL})
    assert response.status_code == 429 and "Retry-After" in response


def test_asking_for_a_link_with_a_bad_address_is_a_field_error(account):
    response = post(APIClient(), RESET, {"email": "nope"})
    assert response.status_code == 400 and "email" in response.json()["fields"]


@pytest.mark.parametrize("url", [RESET, CONFIRM])
def test_the_public_reset_endpoints_demand_a_csrf_token(url):
    assert post(APIClient(enforce_csrf_checks=True), url, {}).status_code == 403


def test_the_change_endpoint_is_bearer_only_no_csrf_but_no_cookie_login_either(account):
    strict = APIClient(enforce_csrf_checks=True)
    strict.cookies = account.cookies  # holds the refresh cookie, which must NOT authenticate
    assert post(strict, PASSWORD_URL, {"current": OLD, "password": NEW}).status_code == 401


def test_the_real_argon2_hasher_works_through_the_whole_reset(client, clock, monkeypatch):
    monkeypatch.setattr(container, "password_hasher", lambda: Argon2PasswordHasher())
    post(client, REGISTER, SIGN_UP)
    code = re.search(r"Your code is (\d{6})\.", mail.outbox[-1].body).group(1)
    post(client, VERIFY, {"email": EMAIL, "code": code})
    clock.advance(31)
    post(APIClient(), RESET, {"email": EMAIL})
    assert post(APIClient(), CONFIRM, {"token": link_token(), "password": NEW}).status_code == 204
    assert stored_password().startswith("argon2$argon2id$") and NEW not in stored_password()
    clock.advance(61)
    assert post(APIClient(), LOGIN, {"email": EMAIL, "password": NEW}).status_code == 200
