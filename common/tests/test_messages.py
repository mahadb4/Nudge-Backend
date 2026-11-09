"""The Messages catalogue: names are the wire codes, values are the English texts."""

import re
from string import Formatter

import pytest

from common.messages import Messages

UPPER_SNAKE = re.compile(r"[A-Z][A-Z0-9]*(_[A-Z0-9]+)+")
ALL = list(Messages)


def placeholders(text: str) -> list[str]:
    return [name for _, name, _, _ in Formatter().parse(text) if name is not None]


def test_there_are_messages():
    assert len(ALL) > 40


@pytest.mark.parametrize("message", ALL, ids=lambda m: m.name)
def test_name_is_upper_snake(message):
    assert UPPER_SNAKE.fullmatch(message.name)


def test_every_name_has_a_known_prefix():
    prefixes = {name.split("_")[0] for name in Messages.__members__}
    assert prefixes == {"COMMON", "AUTH", "TENANCY", "VALIDATION", "EMAIL", "CLI", "TESTDB"}


@pytest.mark.parametrize("message", ALL, ids=lambda m: m.name)
def test_text_is_not_empty(message):
    assert message.value.strip()


def test_texts_are_unique():
    assert len({m.value for m in ALL}) == len(ALL)


def test_no_member_is_an_alias_of_another():
    """StrEnum turns a repeated text into an alias, which would change the wire code. @unique blocks
    it too."""
    assert len(Messages.__members__) == len(ALL)


@pytest.mark.parametrize("message", ALL, ids=lambda m: m.name)
def test_placeholders_are_plain_braces_and_format(message):
    names = placeholders(message.value)
    assert all(name == "" for name in names), "use {} only, no names or numbers"
    rendered = message.render(*["X"] * len(names))
    assert "{" not in rendered and "}" not in rendered


def test_render_fills_values_in_order():
    assert Messages.VALIDATION_TOO_LONG.render(80) == "Use at most 80 characters."
    assert Messages.TESTDB_TABLE_COUNT.render(49, 50).startswith(
        "The test database has 49 tables, expected 50."
    )


def test_render_without_the_values_fails_loudly():
    with pytest.raises(IndexError):
        Messages.VALIDATION_TOO_LONG.render()


def test_texts_without_placeholders_ignore_extra_values():
    assert Messages.AUTH_BAD_CREDENTIALS.render() == "That email and password do not match."


def test_code_is_the_member_name_and_the_text_is_the_value():
    assert Messages.AUTH_BAD_CREDENTIALS.code == "AUTH_BAD_CREDENTIALS"
    assert Messages.AUTH_BAD_CREDENTIALS.name == "AUTH_BAD_CREDENTIALS"
    assert Messages.AUTH_BAD_CREDENTIALS.value == "That email and password do not match."


def test_a_message_is_also_its_text():
    assert Messages.AUTH_BAD_CREDENTIALS == "That email and password do not match."
    assert str(Messages.AUTH_BAD_CREDENTIALS) == "That email and password do not match."


def test_lookup_by_code():
    assert Messages["AUTH_BAD_CREDENTIALS"] is Messages.AUTH_BAD_CREDENTIALS
    with pytest.raises(KeyError):
        Messages["NOT_A_CODE"]


def test_auth_flow_codes_present():
    expected = {
        "AUTH_CODE_SENT",
        "AUTH_RESET_LINK_SENT",
        "AUTH_BAD_CREDENTIALS",
        "AUTH_EMAIL_UNVERIFIED",
        "AUTH_INVALID_CODE",
        "AUTH_CODE_ATTEMPTS_EXCEEDED",
        "AUTH_INVALID_TOKEN",
        "AUTH_WRONG_CURRENT_PASSWORD",
        "AUTH_ACCESS_TOKEN_INVALID",
        "AUTH_SESSION_INVALID",
        "AUTH_CSRF_FAILED",
        "TENANCY_ORGANIZATION_REQUIRED",
    }
    assert expected <= set(Messages.__members__)
