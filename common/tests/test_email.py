"""Email delivery: the strict and the quiet sender, failure logging without secrets, the settings
read from the environment, and send_test_email. No real mail is ever sent: the backends are the
in-memory one, or a fake that fails."""

import logging
import os
import smtplib
import socket
import subprocess
import sys

import pytest
from django.conf import settings
from django.core import mail
from django.core.management import CommandError, call_command
from django.test import override_settings

from common.errors import ServiceUnavailable
from common.infra.email import DjangoEmailSender, QuietEmailSender
from common.interfaces import EmailMessage
from common.tests.fakes import FailingEmailBackend

SECRET = "pa55-word-that-must-never-be-logged"
LOGIN = "smtp-login-user"
FAILING = "common.tests.fakes.FailingEmailBackend"
MESSAGE = EmailMessage(
    to="victim@example.com",
    subject="Your Nudge verification code",
    text_body="Your code is 123456.",
)

ERRORS = [
    smtplib.SMTPAuthenticationError(535, f"5.7.8 bad login {LOGIN} {SECRET}".encode()),
    smtplib.SMTPServerDisconnected(f"server said {SECRET}"),
    smtplib.SMTPRecipientsRefused({"victim@example.com": (550, b"no such user")}),
    smtplib.SMTPConnectError(421, f"busy {SECRET}"),
    TimeoutError(f"timed out talking to {SECRET}"),
    socket.gaierror(-2, f"Name or service not known {SECRET}"),
    ConnectionRefusedError(111, f"refused {SECRET}"),
]


@pytest.fixture
def failing(monkeypatch):
    def use(error: BaseException):
        monkeypatch.setattr(FailingEmailBackend, "error", error)
        monkeypatch.setattr(FailingEmailBackend, "attempts", 0)

    with override_settings(
        EMAIL_BACKEND=FAILING, EMAIL_HOST_PASSWORD=SECRET, EMAIL_HOST_USER=LOGIN
    ):
        yield use


# ---- the senders


def test_the_test_settings_never_use_a_delivering_backend():
    assert settings.EMAIL_BACKEND == "django.core.mail.backends.locmem.EmailBackend"


def test_a_message_goes_out_through_the_backend_with_the_configured_sender():
    DjangoEmailSender().send(MESSAGE)
    (sent,) = mail.outbox
    assert sent.to == ["victim@example.com"] and sent.subject == MESSAGE.subject
    assert sent.from_email == settings.DEFAULT_FROM_EMAIL and "123456" in sent.body


@pytest.mark.parametrize("error", ERRORS, ids=lambda e: type(e).__name__)
def test_every_delivery_failure_is_a_503_error_not_a_crash(failing, error):
    failing(error)
    with pytest.raises(ServiceUnavailable) as info:
        DjangoEmailSender().send(MESSAGE)
    assert info.value.status == 503 and info.value.code == "COMMON_SERVICE_UNAVAILABLE"
    assert info.value.__cause__ is None and SECRET not in str(info.value)


@pytest.mark.parametrize("error", ERRORS, ids=lambda e: type(e).__name__)
def test_the_failure_log_has_the_kind_and_nothing_secret(failing, caplog, error):
    failing(error)
    with caplog.at_level(logging.DEBUG), pytest.raises(ServiceUnavailable):
        DjangoEmailSender().send(MESSAGE)
    records = [r for r in caplog.records if r.name == "common.infra.email"]
    assert len(records) == 1 and records[0].levelno == logging.ERROR
    text = caplog.text + records[0].getMessage()
    assert type(error).__name__ in text
    for forbidden in (SECRET, LOGIN, "victim@example.com", "123456", settings.DEFAULT_FROM_EMAIL):
        assert forbidden not in text
    assert records[0].exc_info is None  # no traceback, which could quote the server's reply


def test_the_smtp_status_code_is_logged_when_there_is_one(failing, caplog):
    failing(ERRORS[0])
    with caplog.at_level(logging.ERROR), pytest.raises(ServiceUnavailable):
        DjangoEmailSender().send(MESSAGE)
    assert "smtp_code=535" in caplog.text


def test_the_quiet_sender_swallows_a_delivery_failure_but_the_log_stays(failing, caplog):
    failing(smtplib.SMTPServerDisconnected("down"))
    with caplog.at_level(logging.ERROR):
        assert QuietEmailSender(DjangoEmailSender()).send(MESSAGE) is None
    assert FailingEmailBackend.attempts == 1 and "Email delivery failed" in caplog.text


def test_the_quiet_sender_still_delivers_when_all_is_well():
    QuietEmailSender(DjangoEmailSender()).send(MESSAGE)
    assert len(mail.outbox) == 1


def test_the_quiet_sender_hides_only_delivery_failures():
    class Broken:
        def send(self, message: EmailMessage) -> None:
            raise ValueError("a bug, not a delivery failure")

    with pytest.raises(ValueError):
        QuietEmailSender(Broken()).send(MESSAGE)


def test_the_container_gives_strict_and_quiet_senders():
    from common.infra.email import HtmlEmailSender
    from config import container

    assert isinstance(container.email_sender(), HtmlEmailSender)
    assert isinstance(container.email_sender()._inner, DjangoEmailSender)
    assert isinstance(container.quiet_email_sender(), QuietEmailSender)


# ---- send_test_email


def test_send_test_email_refuses_under_the_test_settings_and_sends_nothing():
    with pytest.raises(CommandError) as info:
        call_command("send_test_email", "me@example.com")
    assert "send_test_email" in str(info.value) and "config.settings.dev" in str(info.value)
    assert mail.outbox == []


@pytest.mark.parametrize(
    "override",
    [
        {"settings_module": "config.settings.prod"},
        {"debug": False},
        {"database_name": "nudge_test"},
    ],
)
def test_the_guard_for_send_test_email_is_the_seed_demo_guard(override):
    from common.management.guard import assert_dev_only

    good = dict(
        settings_module="config.settings.dev", debug=True, database_name="n", dev_database_name="n"
    )
    assert_dev_only("send_test_email", **good)
    with pytest.raises(CommandError):
        assert_dev_only("send_test_email", **{**good, **override})


# ---- settings read from the environment (a fresh process each, so nothing leaks between cases)

KEYS = {
    "SECRET_KEY": "s" * 64,
    "JWT_SIGNING_KEY": "j" * 64,
    "EMAIL_HASH_KEY": "h" * 64,
    "DATABASE_URL": "postgres://postgres@localhost:5432/nudge",
    "NUDGE_ENV_FILE": os.devnull,  # ignore the real .env
}
SHOW = (
    "from django.conf import settings as s;"
    "print(s.EMAIL_BACKEND, s.EMAIL_HOST, s.EMAIL_PORT, s.EMAIL_USE_TLS, repr(s.EMAIL_HOST_USER),"
    " s.EMAIL_TIMEOUT, s.DEFAULT_FROM_EMAIL)"
)


def run_with(module: str, env: dict[str, str], code: str = SHOW) -> subprocess.CompletedProcess:
    clean = {k: v for k, v in os.environ.items() if not k.startswith("EMAIL_")}
    clean.pop("DEFAULT_FROM_EMAIL", None)
    return subprocess.run(
        [sys.executable, "-c", f"import django; django.setup(); {code}"],
        cwd=settings.BASE_DIR,
        env={**clean, **KEYS, "DJANGO_SETTINGS_MODULE": module, **env},
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_development_defaults_to_the_console_backend_with_a_ten_second_timeout():
    result = run_with("config.settings.dev", {})
    assert result.returncode == 0, result.stderr
    backend, host, port, tls, user, timeout, sender = result.stdout.split(maxsplit=6)[:7]
    assert backend == "django.core.mail.backends.console.EmailBackend"
    assert (host, port, tls, user, timeout) == ("localhost", "25", "False", "''", "10")
    assert sender.startswith("Nudge")


def test_smtp_is_used_only_when_the_environment_says_so_and_every_name_is_read():
    env = {
        "EMAIL_BACKEND": "django.core.mail.backends.smtp.EmailBackend",
        "EMAIL_HOST": "smtp.example.com",
        "EMAIL_PORT": "587",
        "EMAIL_USE_TLS": "True",
        "EMAIL_HOST_USER": "mailer",
        "EMAIL_HOST_PASSWORD": SECRET,
        "EMAIL_TIMEOUT": "7",
        "DEFAULT_FROM_EMAIL": "Nudge <hello@example.com>",
    }
    code = SHOW + f";print(s.EMAIL_HOST_PASSWORD == {SECRET!r})"
    result = run_with("config.settings.dev", env, code)
    assert result.returncode == 0, result.stderr
    first, second = result.stdout.strip().splitlines()
    assert first == (
        "django.core.mail.backends.smtp.EmailBackend smtp.example.com 587 True 'mailer' 7 "
        "Nudge <hello@example.com>"
    )
    assert second == "True" and SECRET not in first


@pytest.mark.parametrize("timeout", ["0", "-5"])
def test_a_non_positive_timeout_stops_the_start_without_printing_the_password(timeout):
    result = run_with(
        "config.settings.dev", {"EMAIL_TIMEOUT": timeout, "EMAIL_HOST_PASSWORD": SECRET}
    )
    assert result.returncode != 0 and "EMAIL_TIMEOUT" in result.stderr
    assert SECRET not in result.stderr + result.stdout


def test_production_refuses_a_backend_that_delivers_nothing():
    base = {"ALLOWED_HOSTS": "example.com", "CACHE_URL": "redis://localhost:6379/0"}
    refused = run_with("config.settings.prod", {**base, "EMAIL_HOST_PASSWORD": SECRET})
    assert refused.returncode != 0 and "EMAIL_BACKEND" in refused.stderr
    assert SECRET not in refused.stderr + refused.stdout
    smtp = "django.core.mail.backends.smtp.EmailBackend"
    allowed = run_with("config.settings.prod", {**base, "EMAIL_BACKEND": smtp})
    assert allowed.returncode == 0, allowed.stderr


def test_the_env_example_lists_the_names_and_no_value_for_the_secret():
    text = (settings.BASE_DIR / ".env.example").read_text(encoding="utf-8")
    for name in (
        "EMAIL_BACKEND",
        "EMAIL_HOST",
        "EMAIL_PORT",
        "EMAIL_USE_TLS",
        "EMAIL_HOST_USER",
        "EMAIL_HOST_PASSWORD",
        "DEFAULT_FROM_EMAIL",
        "EMAIL_TIMEOUT",
    ):
        assert name in text
    for line in text.splitlines():
        if line.lstrip("# ").startswith("EMAIL_HOST_PASSWORD="):
            assert line.split("=", 1)[1].strip() == ""
    assert "EMAIL_URL" not in text
