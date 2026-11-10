"""When SMTP fails or times out, every path that sends mail still answers as if it worked, so the
reply never reveals whether an address exists, and a failure log (without secrets) is written. The
backend is a fake that fails: no network, no real mail."""

import logging
import re
import smtplib

import pytest
from django.core import mail
from django.db import connection
from django.test import override_settings
from rest_framework.test import APIClient

from apps.accounts.tests.fakes import VALID_REGISTRATION
from common.tests.fakes import FailingEmailBackend

pytestmark = pytest.mark.django_db

API = "/api/v1/auth/"
REGISTER, VERIFY, RESEND, LOGIN, RESET, CONFIRM, PASSWORD = (
    f"{API}{name}/"
    for name in ("register", "verify", "resend", "login", "reset", "reset/confirm", "password")
)
EMAIL = VALID_REGISTRATION["email"]
OLD = VALID_REGISTRATION["password"]
NEW = "Copper-Meadow-Gate-55"
SECRET = "pa55-word-that-must-never-be-logged"
BODY = {**VALID_REGISTRATION, "type": VALID_REGISTRATION["account_type"]}
del BODY["account_type"]
UNKNOWN = "nobody@example.com"


def post(client: APIClient, url: str, data: object = None, **extra: str):
    return client.post(url, data if data is not None else {}, format="json", **extra)


class Outage:
    """A failing mail backend that can be switched off again ("SMTP is back")."""

    def __init__(self) -> None:
        self._override = override_settings(
            EMAIL_BACKEND="common.tests.fakes.FailingEmailBackend",
            EMAIL_HOST_PASSWORD=SECRET,
            EMAIL_HOST_USER="smtp-login-user",
        )
        self._active = False

    def start(self) -> "Outage":
        if not self._active:
            self._override.enable()
            self._active = True
        return self

    def disable(self) -> None:
        if self._active:
            self._override.disable()
            self._active = False


@pytest.fixture
def broken(monkeypatch, request):
    """Call it to make the mail backend fail from now on. It returns the Outage, so a test can end
    it."""

    def switch(error: BaseException | None = None) -> Outage:
        monkeypatch.setattr(
            FailingEmailBackend, "error", error or smtplib.SMTPServerDisconnected(f"down {SECRET}")
        )
        monkeypatch.setattr(FailingEmailBackend, "attempts", 0)
        outage = Outage().start()
        request.addfinalizer(outage.disable)
        return outage

    return switch


def code_from(outbox_message) -> str:
    return re.search(r"Your code is (\d{6})\.", outbox_message.body).group(1)


def user_count() -> int:
    with connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM users")
        return cursor.fetchone()[0]


def sign_up_and_verify(client, clock) -> str:
    """A verified account, made while mail still works. Returns an access token."""
    post(client, REGISTER, BODY)
    verified = post(client, VERIFY, {"email": EMAIL, "code": code_from(mail.outbox[-1])})
    clock.advance(31)
    mail.outbox.clear()
    return verified.json()["access"]


# ---- register


def test_register_answers_202_when_smtp_fails_and_the_account_exists_anyway(client, broken, caplog):
    working = post(
        APIClient(), REGISTER, {**BODY, "email": "other@example.com", "name": "Sana Malik"}
    )
    broken()
    with caplog.at_level(logging.ERROR):
        response = post(client, REGISTER, BODY)
    assert response.status_code == 202 and response.json() == working.json()
    assert user_count() == 2 and FailingEmailBackend.attempts == 1
    assert "Email delivery failed" in caplog.text


def test_register_looks_the_same_for_a_known_address_when_smtp_fails(client, clock, broken):
    sign_up_and_verify(client, clock)
    broken()
    known = post(APIClient(), REGISTER, BODY)  # a verified address: the notice fails to send
    clock.advance(31)
    new = post(APIClient(), REGISTER, {**BODY, "email": "fresh@example.com", "name": "Sana Malik"})
    assert (known.status_code, known.json()) == (new.status_code, new.json()) == (202, known.json())


def test_register_with_a_timeout_is_the_same_202(client, broken):
    broken(TimeoutError("timed out"))
    assert post(client, REGISTER, BODY).status_code == 202


def test_the_failure_log_of_a_registration_holds_no_secret_or_address(client, broken, caplog):
    broken(smtplib.SMTPAuthenticationError(535, f"bad login {SECRET}".encode()))
    with caplog.at_level(logging.DEBUG):
        response = post(client, REGISTER, BODY)
    text = caplog.text
    assert response.status_code == 202
    for forbidden in (SECRET, "smtp-login-user", EMAIL, "Your code is"):
        assert forbidden not in text and forbidden not in response.content.decode()
    assert "SMTPAuthenticationError" in text and "smtp_code=535" in text


# ---- resend


def test_resend_is_202_and_identical_for_known_and_unknown_addresses_when_smtp_fails(
    client, clock, broken
):
    post(client, REGISTER, BODY)  # unverified, with a live code
    clock.advance(31)
    broken()
    known = post(APIClient(), RESEND, {"email": EMAIL})
    unknown = post(APIClient(), RESEND, {"email": UNKNOWN})
    assert (known.status_code, known.json()) == (unknown.status_code, unknown.json())
    assert known.status_code == 202 and FailingEmailBackend.attempts == 1  # only the real one tried


def test_a_new_code_works_once_smtp_is_back(client, clock, broken):
    post(client, REGISTER, BODY)
    clock.advance(31)
    override = broken()
    assert post(APIClient(), RESEND, {"email": EMAIL}).status_code == 202
    override.disable()  # SMTP is back
    clock.advance(31)
    assert post(APIClient(), RESEND, {"email": EMAIL}).status_code == 202
    code = code_from(mail.outbox[-1])
    assert post(client, VERIFY, {"email": EMAIL, "code": code}).status_code == 200


# ---- forgot password and the notices after a committed change


def test_forgot_password_does_not_reveal_whether_the_address_exists_when_smtp_fails(
    client, clock, broken
):
    sign_up_and_verify(client, clock)
    broken()
    known = post(APIClient(), RESET, {"email": EMAIL})
    unknown = post(APIClient(), RESET, {"email": UNKNOWN})
    assert (known.status_code, known.json()) == (unknown.status_code, unknown.json())
    assert known.status_code == 202 and FailingEmailBackend.attempts == 1


def test_a_password_change_stays_a_success_when_only_the_notice_fails(client, clock, broken):
    token = sign_up_and_verify(client, clock)
    broken()
    response = post(
        APIClient(),
        PASSWORD,
        {"current": OLD, "password": NEW},
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert response.status_code == 204
    clock.advance(61)
    assert post(APIClient(), LOGIN, {"email": EMAIL, "password": NEW}).status_code == 200


def test_a_reset_stays_a_success_when_only_the_notice_fails(client, clock):
    sign_up_and_verify(client, clock)
    post(APIClient(), RESET, {"email": EMAIL})
    link = re.search(r"token=([\w-]+)", mail.outbox[-1].body).group(1)
    override = override_settings(EMAIL_BACKEND="common.tests.fakes.FailingEmailBackend")
    with override:
        response = post(APIClient(), CONFIRM, {"token": link, "password": NEW})
    assert response.status_code == 204
    clock.advance(61)
    assert post(APIClient(), LOGIN, {"email": EMAIL, "password": NEW}).status_code == 200


def test_no_error_body_or_log_line_ever_carries_the_smtp_password(client, clock, broken, caplog):
    sign_up_and_verify(client, clock)
    broken(smtplib.SMTPServerDisconnected(f"server echoed {SECRET}"))
    with caplog.at_level(logging.DEBUG):
        replies = [
            post(APIClient(), RESET, {"email": EMAIL}),
            post(APIClient(), RESET, {"email": UNKNOWN}),
            post(APIClient(), RESEND, {"email": EMAIL}),
            post(APIClient(), REGISTER, {**BODY, "email": "z@example.com", "name": "Sana Malik"}),
        ]
    for reply in replies:
        assert SECRET not in reply.content.decode() and SECRET not in str(reply.headers)
    assert SECRET not in caplog.text
