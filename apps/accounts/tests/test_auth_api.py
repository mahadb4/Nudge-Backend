"""The auth endpoints over HTTP, with the real services, repositories and database (nudge_test)."""

import json
import re
from datetime import UTC, datetime
from uuid import UUID

import pytest
from django.core import mail
from django.core.cache import caches
from django.db import connection
from rest_framework.test import APIClient

from apps.accounts.tests.fakes import VALID_REGISTRATION
from common.errors import ServiceUnavailable
from common.infra.cache import DjangoCache
from common.security.argon2_password_hasher import Argon2PasswordHasher
from common.security.refresh_tokens import sha256_hex, split_refresh_value
from config import container

pytestmark = pytest.mark.django_db

REGISTER, VERIFY, RESEND, CSRF = (
    f"/api/v1/auth/{name}/" for name in ("register", "verify", "resend", "csrf")
)
BODY = {**VALID_REGISTRATION}
BODY["type"] = BODY.pop("account_type")  # on the wire the field is called "type"


def post(client: APIClient, url: str, data: object, **extra: str):
    return client.post(url, data, format="json", **extra)


def count(table: str) -> int:
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT count(*) FROM {table}")
        return cursor.fetchone()[0]


def audit_actions() -> list[str]:
    with connection.cursor() as cursor:
        cursor.execute("SELECT action FROM audit_logs ORDER BY id")
        return [row[0] for row in cursor.fetchall()]


def emailed_code() -> str:
    match = re.search(r"Your code is (\d{6})\.", mail.outbox[-1].body)
    assert match
    return match.group(1)


def fields(response) -> dict[str, list[str]]:
    return {name: [i["code"] for i in issues] for name, issues in response.json()["fields"].items()}


# ---- CSRF


def test_csrf_endpoint_sets_the_cookie_and_returns_the_token(client):
    response = client.get(CSRF)
    assert response.status_code == 200 and response["Cache-Control"] == "no-store"
    assert response.json()["csrf_token"] and "csrftoken" in response.cookies
    assert not response.cookies["csrftoken"]["httponly"]  # the frontend must be able to read it


def test_a_post_without_a_csrf_token_is_refused():
    strict = APIClient(enforce_csrf_checks=True)
    response = post(strict, REGISTER, BODY)
    assert response.status_code == 403
    assert response.json() == {
        "code": "AUTH_CSRF_FAILED",
        "detail": "Reload the page and try again.",
    }
    assert count("users") == 0


def test_a_post_with_a_wrong_csrf_token_is_refused():
    strict = APIClient(enforce_csrf_checks=True)
    strict.get(CSRF)
    assert post(strict, REGISTER, BODY, HTTP_X_CSRFTOKEN="not-the-token").status_code == 403


def test_a_post_with_the_right_csrf_token_goes_through():
    strict = APIClient(enforce_csrf_checks=True)
    token = strict.get(CSRF).json()["csrf_token"]
    assert post(strict, REGISTER, BODY, HTTP_X_CSRFTOKEN=token).status_code == 202


@pytest.mark.parametrize("url", [REGISTER, VERIFY, RESEND])
def test_every_cookie_endpoint_demands_a_csrf_token(url):
    assert post(APIClient(enforce_csrf_checks=True), url, {}).status_code == 403


# ---- register


def test_a_business_registers(client):
    response = post(client, REGISTER, BODY)
    assert response.status_code == 202
    assert response.json() == {
        "code": "AUTH_CODE_SENT",
        "detail": (
            "If this email can be used, a 6-digit code is on its way. It expires in 10 minutes."
        ),
    }
    assert not response.cookies  # nobody is signed in yet
    assert response["Cache-Control"] == "no-store"
    assert [count(t) for t in ("users", "organizations", "memberships", "deal_stages")] == [
        1,
        1,
        1,
        7,
    ]
    with connection.cursor() as cursor:
        cursor.execute("SELECT name, account_type FROM organizations")
        assert cursor.fetchall() == [("Acme Sales", 2)]
        cursor.execute("SELECT role, status FROM memberships")
        assert cursor.fetchall() == [(1, 1)]
        cursor.execute("SELECT email, full_name, email_verified_at FROM users")
        assert cursor.fetchall() == [("ali@example.com", "Ali Raza", None)]
    assert audit_actions() == ["user.register"]
    assert [m.to for m in mail.outbox] == [["ali@example.com"]] and re.fullmatch(
        r"\d{6}", emailed_code()
    )


def test_an_individual_registers_without_a_company(client):
    body = {**BODY, "type": "individual"}
    del body["company"]
    assert post(client, REGISTER, body).status_code == 202
    with connection.cursor() as cursor:
        cursor.execute("SELECT name, account_type FROM organizations")
        assert cursor.fetchall() == [("Ali Raza", 1)]


def test_a_known_address_gets_the_same_response_and_no_new_rows(client, clock):
    first = post(client, REGISTER, BODY)
    clock.advance(31)
    second = post(
        client, REGISTER, {**BODY, "name": "Someone Else", "password": "Another-Password-77"}
    )
    assert (first.status_code, first.json()) == (second.status_code, second.json())
    assert [count(t) for t in ("users", "organizations", "memberships")] == [1, 1, 1]


def test_an_unverified_address_is_overwritten_by_the_latest_sign_up(client, clock):
    assert post(client, REGISTER, BODY).status_code == 202
    first_code = emailed_code()
    clock.advance(31)
    second = {**BODY, "name": "Sana Malik", "password": "Copper-Meadow-Gate-55"}
    assert post(client, REGISTER, second).status_code == 202
    assert [count(t) for t in ("users", "organizations", "memberships")] == [1, 1, 1]
    assert "user.register_replace" in audit_actions()
    stale = post(client, VERIFY, {"email": BODY["email"], "code": first_code})
    assert stale.status_code == 400
    ok = post(client, VERIFY, {"email": BODY["email"], "code": emailed_code()})
    assert ok.status_code == 200
    with connection.cursor() as cursor:
        cursor.execute("SELECT full_name FROM users")
        assert cursor.fetchall() == [("Sana Malik",)]


def test_the_password_is_hashed_with_argon2_in_the_database(client, monkeypatch):
    monkeypatch.setattr(container, "password_hasher", lambda: Argon2PasswordHasher())
    assert post(client, REGISTER, BODY).status_code == 202
    with connection.cursor() as cursor:
        cursor.execute("SELECT password FROM users")
        (stored,) = cursor.fetchone()
    assert stored.startswith("argon2$argon2id$") and "Harbor-Lantern-42" not in stored
    assert Argon2PasswordHasher().verify("Harbor-Lantern-42", stored) is True


def test_a_failure_halfway_rolls_back_every_table(client, monkeypatch):
    class BrokenSeeder:
        def seed_defaults(self, organization_id: UUID) -> list[object]:
            raise ServiceUnavailable()

    monkeypatch.setattr(container, "stage_service", lambda: BrokenSeeder())
    response = post(client, REGISTER, BODY)
    assert response.status_code == 503 and response.json()["code"] == "COMMON_SERVICE_UNAVAILABLE"
    assert [
        count(t) for t in ("users", "organizations", "memberships", "deal_stages", "audit_logs")
    ] == [0] * 5
    assert not mail.outbox


def test_with_the_cache_down_registration_is_refused_not_unprotected(client, monkeypatch):
    class DownBackend:
        def incr(self, *args: object) -> int:
            raise OSError("cache down")

        add = get = set = delete = incr

    monkeypatch.setattr(container, "cache_store", lambda: DjangoCache(DownBackend()))
    assert post(client, REGISTER, BODY).status_code == 503
    assert count("users") == 0


def test_a_forged_forwarded_for_header_does_not_dodge_the_ip_limit(client):
    for index in range(10):
        response = post(
            client,
            REGISTER,
            {**BODY, "email": f"user{index}@example.com"},
            HTTP_X_FORWARDED_FOR=f"10.1.1.{index}",
        )
        assert response.status_code == 202
    blocked = post(
        client, REGISTER, {**BODY, "email": "user10@example.com"}, HTTP_X_FORWARDED_FOR="10.1.1.99"
    )
    assert blocked.status_code == 429 and blocked["Retry-After"].isdigit()
    assert blocked.json()["code"] == "COMMON_RATE_LIMITED"


# ---- register: bad input


def test_an_empty_body_reports_every_required_field(client):
    response = post(client, REGISTER, {})
    assert response.status_code == 400 and response.json()["code"] == "COMMON_VALIDATION_FAILED"
    assert fields(response) == {
        "type": ["VALIDATION_REQUIRED"],
        "name": ["VALIDATION_REQUIRED"],
        "email": ["VALIDATION_REQUIRED"],
        "timezone": ["VALIDATION_REQUIRED"],
        "password": ["VALIDATION_REQUIRED"],
    }


def test_unknown_fields_are_refused_and_nothing_is_created(client):
    response = post(client, REGISTER, {**BODY, "is_staff": True, "role": "owner"})
    assert response.status_code == 400
    assert fields(response) == {
        "is_staff": ["VALIDATION_UNKNOWN_FIELD"],
        "role": ["VALIDATION_UNKNOWN_FIELD"],
    }
    assert count("users") == 0


def test_a_capitalised_account_type_is_refused(client):
    assert fields(post(client, REGISTER, {**BODY, "type": "Business"})) == {
        "type": ["VALIDATION_CHOICE_INVALID"]
    }


def test_an_individual_with_a_company_is_refused(client):
    assert fields(post(client, REGISTER, {**BODY, "type": "individual"})) == {
        "company": ["VALIDATION_COMPANY_NOT_ALLOWED"]
    }


def test_wrong_json_types_are_refused_not_crashed_on(client):
    response = post(
        client,
        REGISTER,
        {**BODY, "name": 5, "email": ["a@b.co"], "password": {"x": 1}, "timezone": True},
    )
    assert response.status_code == 400
    assert all(codes == ["VALIDATION_INVALID_TYPE"] for codes in fields(response).values())


def test_a_body_that_is_not_an_object_is_refused(client):
    for body in ([], ["a"], "text", 5):
        response = post(client, REGISTER, body)
        assert response.status_code == 400 and fields(response) == {
            "non_field_errors": ["VALIDATION_INVALID_TYPE"]
        }


def test_malformed_json_is_a_clean_400(client):
    response = client.post(REGISTER, '{"name": ', content_type="application/json")
    assert response.status_code == 400 and response.json()["code"] == "COMMON_MALFORMED_JSON"


def test_a_form_post_is_refused(client):
    response = client.post(REGISTER, "name=Ali", content_type="application/x-www-form-urlencoded")
    assert response.status_code == 400 and response.json()["code"] == "COMMON_INVALID_CONTENT_TYPE"


def test_a_control_character_in_a_name_is_refused(client):
    assert fields(post(client, REGISTER, {**BODY, "name": "Ali\u0000Raza"})) == {
        "name": ["VALIDATION_CONTROL_CHARS"]
    }


def test_a_oversized_body_is_refused(client):
    response = client.post(
        REGISTER, json.dumps({**BODY, "name": "x" * 1_100_000}), content_type="application/json"
    )
    assert response.status_code == 400 and response.json()["code"] == "COMMON_BODY_TOO_LARGE"


def test_get_is_not_allowed_on_register(client):
    response = client.get(REGISTER)
    assert response.status_code == 405 and response.json()["code"] == "COMMON_METHOD_NOT_ALLOWED"


# ---- verify


def register_and_verify(client: APIClient):
    post(client, REGISTER, BODY)
    return post(client, VERIFY, {"email": "ali@example.com", "code": emailed_code()})


def test_verifying_returns_the_access_token_the_user_and_the_refresh_cookie(client):
    response = register_and_verify(client)
    assert response.status_code == 200 and response["Cache-Control"] == "no-store"
    body = response.json()
    assert set(body) == {"access", "user"}
    user = body["user"]
    assert (user["name"], user["email"], user["type"], user["verified"], user["role"]) == (
        "Ali Raza",
        "ali@example.com",
        "business",
        True,
        "owner",
    )
    assert (
        user["organization"]["name"] == "Acme Sales" and user["organization"]["type"] == "business"
    )
    assert [o["name"] for o in user["organizations"]] == ["Acme Sales"] and user["phone"] is None
    assert "password" not in json.dumps(body) and "argon2" not in json.dumps(body)


def test_the_refresh_cookie_is_httponly_scoped_and_a_session_cookie(client):
    cookie = register_and_verify(client).cookies["nudge_refresh"]
    assert (
        cookie["httponly"] is True
        and cookie["path"] == "/api/v1/auth/"
        and cookie["samesite"] == "Lax"
    )
    assert cookie["max-age"] == ""  # a session cookie
    assert not cookie["secure"]  # local development; production settings turn it on


def test_only_a_hash_of_the_refresh_value_is_stored(client):
    value = register_and_verify(client).cookies["nudge_refresh"].value
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT id, refresh_token_hash, user_id, revoked_at, host(ip_address) "
            "FROM user_sessions"
        )
        ((session_id, stored, _, revoked_at, ip),) = cursor.fetchall()
    assert (
        split_refresh_value(value) == session_id
        and stored == sha256_hex(value)
        and value not in stored
    )
    assert revoked_at is None and ip == "127.0.0.1"


def test_the_access_token_is_valid_and_names_the_session(client):
    body = register_and_verify(client).json()
    claims = container.token_signer().verify_access(body["access"], now=datetime.now(UTC))
    with connection.cursor() as cursor:
        cursor.execute("SELECT id, user_id FROM user_sessions")
        assert cursor.fetchall() == [(claims.session_id, claims.user_id)]
    assert str(claims.user_id) == body["user"]["id"]


def test_verifying_marks_the_email_verified_and_audits_it(client):
    register_and_verify(client)
    with connection.cursor() as cursor:
        cursor.execute("SELECT email_verified_at IS NOT NULL FROM users")
        assert cursor.fetchone() == (True,)
    assert audit_actions() == ["user.register", "user.email_verify"]


def test_a_code_cannot_be_used_twice(client):
    post(client, REGISTER, BODY)
    code = emailed_code()
    assert post(client, VERIFY, {"email": "ali@example.com", "code": code}).status_code == 200
    again = post(client, VERIFY, {"email": "ali@example.com", "code": code})
    assert again.status_code == 400 and again.json()["code"] == "AUTH_INVALID_CODE"
    assert count("user_sessions") == 1


def test_a_wrong_code_is_a_fixed_400_and_creates_no_session(client):
    post(client, REGISTER, BODY)
    wrong = "000000" if emailed_code() != "000000" else "111111"
    response = post(client, VERIFY, {"email": "ali@example.com", "code": wrong})
    assert response.status_code == 400
    assert response.json() == {
        "code": "AUTH_INVALID_CODE",
        "detail": "That code is not valid or has expired.",
    }
    assert not response.cookies and count("user_sessions") == 0


def test_the_sixth_wrong_code_is_a_429_even_with_the_right_code(client):
    post(client, REGISTER, BODY)
    right = emailed_code()
    wrong = "000000" if right != "000000" else "111111"
    for _ in range(5):
        assert post(client, VERIFY, {"email": "ali@example.com", "code": wrong}).status_code == 400
    response = post(client, VERIFY, {"email": "ali@example.com", "code": right})
    assert response.status_code == 429 and response["Retry-After"] == "30"
    assert response.json()["code"] == "AUTH_CODE_ATTEMPTS_EXCEEDED"
    assert count("user_sessions") == 0


def test_an_unknown_email_gets_the_same_answer_as_a_wrong_code(client):
    post(client, REGISTER, BODY)
    wrong = "000000" if emailed_code() != "000000" else "111111"
    known = post(client, VERIFY, {"email": "ali@example.com", "code": wrong})
    unknown = post(client, VERIFY, {"email": "nobody@example.com", "code": wrong})
    assert (known.status_code, known.json()) == (unknown.status_code, unknown.json())


def test_a_badly_formed_code_names_the_field(client):
    response = post(client, VERIFY, {"email": "ali@example.com", "code": "12ab"})
    assert response.status_code == 400 and fields(response) == {"code": ["VALIDATION_CODE_FORMAT"]}


def test_an_expired_code_is_refused(client, clock, monkeypatch):
    post(client, REGISTER, BODY)
    code = emailed_code()
    caches[
        "default"
    ].clear()  # the cache entry expired (10 minutes) -- the real cache cannot be fast-forwarded
    response = post(client, VERIFY, {"email": "ali@example.com", "code": code})
    assert response.status_code == 400 and response.json()["code"] == "AUTH_INVALID_CODE"


# ---- resend


def test_resend_sends_a_new_code(client, clock):
    post(client, REGISTER, BODY)
    clock.advance(31)
    response = post(client, RESEND, {"email": "ali@example.com"})
    assert response.status_code == 202 and response.json()["code"] == "AUTH_CODE_SENT"
    assert len(mail.outbox) == 2
    assert (
        post(client, VERIFY, {"email": "ali@example.com", "code": emailed_code()}).status_code
        == 200
    )


def test_resend_within_30_seconds_is_refused_with_retry_after(client, clock):
    post(client, REGISTER, BODY)
    response = post(client, RESEND, {"email": "ali@example.com"})
    assert response.status_code == 429 and response.json()["code"] == "COMMON_RATE_LIMITED"
    assert 1 <= int(response["Retry-After"]) <= 30


def test_resend_answers_the_same_for_an_unknown_address(client):
    known_register = post(client, REGISTER, BODY)
    unknown = post(client, RESEND, {"email": "nobody@example.com"})
    assert (unknown.status_code, unknown.json()) == (
        known_register.status_code,
        known_register.json(),
    )
    assert len(mail.outbox) == 1  # nothing was sent to the unknown address


def test_resend_checks_the_email_format(client):
    assert fields(post(client, RESEND, {"email": "nope"})) == {
        "email": ["VALIDATION_EMAIL_INVALID"]
    }
    assert fields(post(client, RESEND, {})) == {"email": ["VALIDATION_REQUIRED"]}
    assert fields(post(client, RESEND, {"email": "a@b.co", "x": 1})) == {
        "x": ["VALIDATION_UNKNOWN_FIELD"]
    }
