"""Hashing, access tokens, refresh values, client IP, cookies, the email sender and the strict
serializer."""

import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt
import pytest
from django.core import mail
from django.http import HttpResponse
from rest_framework import exceptions as drf

from common.constants import JWT_ALGORITHM, Cookie, Ttl
from common.errors import ServiceUnavailable, Unauthorized
from common.infra.email import DjangoEmailSender
from common.interfaces import EmailMessage
from common.responses import exception_handler
from common.security.argon2_password_hasher import Argon2PasswordHasher
from common.security.client_ip import client_ip
from common.security.cookies import clear_refresh_cookie, set_refresh_cookie
from common.security.hmac_hasher import HmacHasher
from common.security.jwt_token_signer import JwtTokenSigner
from common.security.refresh_tokens import new_refresh_value, sha256_hex, split_refresh_value
from common.serializers import StrictSerializer, raw_field

NOW = datetime(2026, 11, 9, 12, 0, 0, tzinfo=UTC)
USER = UUID("01a19be3-8259-7cb7-ae0e-6158c9870a6c")
SESSION = UUID("01a19be3-8259-7cb7-ae0e-6158c9870a6d")
KEY = (
    "signing-key-" + "k" * 52
)  # 64 bytes: long enough for every HMAC size, so PyJWT has nothing to warn about
OTHER_KEY = "another-key-" + "o" * 52


# ---- HMAC hasher


def test_hmac_is_stable_keyed_and_separated_by_namespace():
    hasher = HmacHasher("key-one")
    assert hasher.digest("email", "a@b.co") == hasher.digest("email", "a@b.co")
    assert len(hasher.digest("email", "a@b.co")) == 64
    assert hasher.digest("email", "a@b.co") != hasher.digest("verify_code", "a@b.co")
    assert hasher.digest("email", "a@b.co") != HmacHasher("key-two").digest("email", "a@b.co")
    assert "a@b.co" not in hasher.digest("email", "a@b.co")


# ---- Argon2 password hasher (slow on purpose: kept to a few calls)


def test_argon2_hash_format_and_verify():
    hasher = Argon2PasswordHasher()
    encoded = hasher.hash("Harbor-Lantern-42")
    assert encoded.startswith("argon2$argon2id$")
    assert len(encoded) <= 128  # fits users.password
    assert hasher.verify("Harbor-Lantern-42", encoded) is True
    assert hasher.verify("Harbor-Lantern-43", encoded) is False
    assert hasher.needs_rehash(encoded) is False
    assert hasher.hash("Harbor-Lantern-42") != encoded  # random salt
    hasher.dummy_verify("anything")  # same work as verify, raises nothing


# ---- access tokens


def test_access_token_round_trip():
    signer = JwtTokenSigner(KEY)
    issued = signer.issue_access(user_id=USER, session_id=SESSION, now=NOW)
    claims = signer.verify_access(issued.token, now=NOW)
    assert (claims.user_id, claims.session_id, claims.jti) == (USER, SESSION, issued.jti)
    assert issued.expires_at == NOW + timedelta(seconds=Ttl.ACCESS_TOKEN) == claims.expires_at


def test_access_token_expires_after_10_minutes_by_the_injected_clock():
    signer = JwtTokenSigner(KEY)
    token = signer.issue_access(user_id=USER, session_id=SESSION, now=NOW).token
    signer.verify_access(token, now=NOW + timedelta(seconds=599))
    with pytest.raises(Unauthorized) as info:
        signer.verify_access(token, now=NOW + timedelta(seconds=600))
    assert info.value.code == "AUTH_ACCESS_TOKEN_INVALID"


def test_every_token_has_its_own_jti():
    signer = JwtTokenSigner(KEY)
    a = signer.issue_access(user_id=USER, session_id=SESSION, now=NOW)
    b = signer.issue_access(user_id=USER, session_id=SESSION, now=NOW)
    assert a.jti != b.jti


def good_payload() -> dict[str, object]:
    return {
        "user_id": str(USER),
        "sid": str(SESSION),
        "jti": "x",
        "iat": int(NOW.timestamp()),
        "exp": int(NOW.timestamp()) + 600,
    }


@pytest.mark.parametrize(
    "token",
    [
        "",
        "garbage",
        "a.b.c",
        jwt.encode(good_payload(), OTHER_KEY, algorithm="HS256"),  # wrong key
        jwt.encode(good_payload(), None, algorithm="none"),  # alg=none
        jwt.encode(good_payload(), KEY, algorithm="HS512"),  # another algorithm
        jwt.encode(
            {k: v for k, v in good_payload().items() if k != "sid"}, KEY, algorithm="HS256"
        ),  # missing claim
        jwt.encode({**good_payload(), "user_id": "not-a-uuid"}, KEY, algorithm="HS256"),
    ],
)
def test_bad_tokens_are_refused(token):
    with pytest.raises(Unauthorized):
        JwtTokenSigner(KEY).verify_access(token, now=NOW)


def test_a_tampered_token_is_refused():
    signer = JwtTokenSigner(KEY)
    token = signer.issue_access(user_id=USER, session_id=SESSION, now=NOW).token
    head, body, signature = token.split(".")
    with pytest.raises(Unauthorized):
        signer.verify_access(f"{head}.{body}x.{signature}", now=NOW)


def test_access_tokens_are_signed_with_hs256():
    """HMAC-SHA256. (The SHA512 in an old PyJWT warning came from a test that builds an HS512 token
    on purpose.)"""
    token = JwtTokenSigner(KEY).issue_access(user_id=USER, session_id=SESSION, now=NOW).token
    assert jwt.get_unverified_header(token)["alg"] == "HS256"
    assert JWT_ALGORITHM == "HS256"


def test_the_signer_refuses_a_token_signed_with_another_hmac_size():
    token = jwt.encode(good_payload(), KEY, algorithm="HS512")
    with pytest.raises(Unauthorized):
        JwtTokenSigner(KEY).verify_access(token, now=NOW)


# ---- refresh values


def test_refresh_value_format_and_hash():
    value = new_refresh_value(SESSION)
    assert value.startswith(f"{SESSION}.") and len(value) == 36 + 1 + 43
    assert split_refresh_value(value) == SESSION
    assert new_refresh_value(SESSION) != value
    assert len(sha256_hex(value)) == 64 and value not in sha256_hex(value)


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "x",
        f"{SESSION}",
        f"{SESSION}.short",
        f"{SESSION}." + "!" * 43,
        "../" + f"{SESSION}." + "a" * 43,
    ],
)
def test_malformed_refresh_values_have_no_session(bad):
    assert split_refresh_value(bad) is None


# ---- client IP


@pytest.mark.parametrize(
    ("remote", "forwarded", "trusted", "expected"),
    [
        ("203.0.113.9", None, [], "203.0.113.9"),
        ("203.0.113.9", "1.2.3.4", [], "203.0.113.9"),  # not a trusted proxy: header ignored
        ("10.0.0.1", "198.51.100.7", ["10.0.0.1"], "198.51.100.7"),
        (
            "10.0.0.1",
            "6.6.6.6, 198.51.100.7",
            ["10.0.0.1"],
            "198.51.100.7",
        ),  # the client cannot spoof the left side
        ("10.0.0.1", "198.51.100.7, 10.0.0.2", ["10.0.0.1", "10.0.0.2"], "198.51.100.7"),
        ("10.0.0.1", "garbage", ["10.0.0.1"], "10.0.0.1"),
        ("10.0.0.1", None, ["10.0.0.1"], "10.0.0.1"),
        ("::1", None, [], "::1"),
        ("not-an-ip", None, [], None),
        (None, None, [], None),
    ],
)
def test_client_ip(remote, forwarded, trusted, expected):
    assert client_ip(remote, forwarded, trusted) == expected


# ---- cookies


def test_refresh_cookie_flags_when_remembered():
    response = HttpResponse()
    set_refresh_cookie(response, "value", max_age=30 * 86400)
    cookie = response.cookies[Cookie.REFRESH]
    assert cookie["httponly"] is True
    assert cookie["path"] == "/api/v1/auth/"
    assert cookie["samesite"] == "Lax"
    assert int(cookie["max-age"]) == 30 * 86400


def test_refresh_cookie_is_a_session_cookie_when_not_remembered():
    response = HttpResponse()
    set_refresh_cookie(response, "value", max_age=None)
    assert response.cookies[Cookie.REFRESH]["max-age"] == ""


def test_refresh_cookie_is_cleared_on_the_same_path():
    response = HttpResponse()
    clear_refresh_cookie(response)
    cookie = response.cookies[Cookie.REFRESH]
    assert cookie["path"] == "/api/v1/auth/" and int(cookie["max-age"]) == 0


# ---- email sender


def test_email_is_sent_through_django_mail():
    DjangoEmailSender().send(EmailMessage(to="a@b.co", subject="Hello", text_body="Body"))
    assert [(m.to, m.subject, m.body) for m in mail.outbox] == [(["a@b.co"], "Hello", "Body")]


def test_an_email_failure_becomes_service_unavailable(settings):
    settings.EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    settings.EMAIL_HOST, settings.EMAIL_PORT, settings.EMAIL_TIMEOUT = (
        "127.0.0.1",
        1,
        1,
    )  # nothing listens on port 1
    with pytest.raises(ServiceUnavailable):
        DjangoEmailSender().send(EmailMessage(to="a@b.co", subject="Hello", text_body="Body"))


# ---- strict serializer


class SampleRequest(StrictSerializer):
    name = raw_field()
    type = raw_field(source="account_type")


def test_read_returns_every_declared_key():
    assert SampleRequest.read({"name": "Ali"}) == {"name": "Ali", "account_type": None}
    assert SampleRequest.read({"name": None, "type": "business"}) == {
        "name": None,
        "account_type": "business",
    }
    assert SampleRequest.read({}) == {"name": None, "account_type": None}


def test_values_are_not_converted_so_the_validators_see_the_real_type():
    assert SampleRequest.read({"name": 5, "type": ["x"]}) == {"name": 5, "account_type": ["x"]}


def fields_of(data) -> dict[str, list[str]]:
    with pytest.raises(drf.ValidationError) as info:
        SampleRequest.read(data)
    response = exception_handler(info.value, {"view": None})
    assert response.status_code == 400
    return {
        name: [issue["code"] for issue in issues]
        for name, issues in response.data["fields"].items()
    }


def test_unknown_fields_are_refused_by_name():
    assert fields_of({"name": "a", "is_staff": True}) == {"is_staff": ["VALIDATION_UNKNOWN_FIELD"]}


def test_a_hostile_field_name_is_not_echoed():
    codes = fields_of({"<script>alert(1)</script>": 1})
    assert codes == {"non_field_errors": ["VALIDATION_UNKNOWN_FIELD"]}


@pytest.mark.parametrize("body", [[], "text", 5, [{"name": "a"}]])
def test_a_body_that_is_not_an_object_is_refused(body):
    assert fields_of(body) == {"non_field_errors": ["VALIDATION_INVALID_TYPE"]}


def test_the_error_body_is_json_safe():
    with pytest.raises(drf.ValidationError) as info:
        SampleRequest.read({"x" * 100: 1})
    body = exception_handler(info.value, {"view": None}).data
    assert "x" * 100 not in json.dumps(body)
