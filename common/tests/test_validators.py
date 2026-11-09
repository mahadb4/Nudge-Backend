"""Cases ported from the frontend's tests/unit/validate.test.ts, plus the server-only rules."""

import uuid

import pytest

from common.constants import AccountType
from common.errors import InvalidValue
from common.messages import Messages
from common.validators import (
    is_reset_token_format,
    validate_account_type,
    validate_bool,
    validate_code,
    validate_company_for_type,
    validate_email,
    validate_login_password,
    validate_password,
    validate_person_name,
    validate_timezone,
    validate_uuid,
)

GOOD_PASSWORD = "Harbor-Lantern-42"


def code_of(fn, *args, **kwargs):
    with pytest.raises(InvalidValue) as info:
        fn(*args, **kwargs)
    return info.value.issue.message.name


# ---- email


@pytest.mark.parametrize(
    "value", ["a@b.co", "ali.raza@company.com", "x+tag@sub.example.org", "  ALI@Raza.COM "]
)
def test_email_accepted_and_normalised(value):
    assert validate_email(value) == value.strip().lower()


def test_email_strips_invisible_characters():
    assert validate_email("a​li@x.com") == "ali@x.com"


@pytest.mark.parametrize(
    "value",
    [
        "nope",
        "a@b",
        "a@b.c",
        "a..b@x.com",
        ".a@x.com",
        "a.@x.com",
        "a@-x.com",
        "a b@x.com",
        "a@x.c0m",
        "javascript:alert(1)@x.com",
        "josé@x.com",
        "a@münchen.de",
        "a" * 65 + "@x.com",
    ],
)
def test_email_refused(value):
    assert code_of(validate_email, value) == Messages.VALIDATION_EMAIL_INVALID.name


def test_email_length_limit():
    long = "a@" + "b" * 63 + "." + "c" * 63 + "." + "d" * 63 + "." + "e" * 60 + ".com"
    assert code_of(validate_email, long) == Messages.VALIDATION_TOO_LONG.name


@pytest.mark.parametrize(
    ("value", "code"),
    [
        (None, "VALIDATION_REQUIRED"),
        ("", "VALIDATION_REQUIRED"),
        ("   ", "VALIDATION_REQUIRED"),
        (5, "VALIDATION_INVALID_TYPE"),
        ("a\x00@x.com", "VALIDATION_CONTROL_CHARS"),
    ],
)
def test_email_shape_errors(value, code):
    assert code_of(validate_email, value) == code


# ---- person names


@pytest.mark.parametrize(
    "value",
    ["Ali", "O'Brien", "José", "Anne-Marie", "李雷", "محمد", "Robert'); DROP TABLE users;--"],
)
def test_real_names_pass(value):
    assert validate_person_name(value) == value


@pytest.mark.parametrize(
    ("value", "code"),
    [
        ("", "VALIDATION_REQUIRED"),
        ("   ", "VALIDATION_REQUIRED"),
        ("A", "VALIDATION_TOO_SHORT"),
        ("12345", "VALIDATION_NAME_NEEDS_LETTER"),
        ("٣٤٥٦", "VALIDATION_NAME_NEEDS_LETTER"),
        ("---", "VALIDATION_NAME_NEEDS_LETTER"),
        ("<b>Ali</b>", "VALIDATION_MARKUP_NOT_ALLOWED"),
        ("Ali>", "VALIDATION_MARKUP_NOT_ALLOWED"),
        ("x" * 81, "VALIDATION_TOO_LONG"),
        ("​‌‍", "VALIDATION_REQUIRED"),
        ("Al\x00i", "VALIDATION_CONTROL_CHARS"),
    ],
)
def test_bad_names_refused(value, code):
    assert code_of(validate_person_name, value) == code


def test_name_is_cleaned():
    assert validate_person_name("  Ali \n  Raza ") == "Ali Raza"


def test_very_long_name_is_refused_not_truncated():
    assert code_of(validate_person_name, "x" * 10_000) == "VALIDATION_TOO_LONG"


# ---- passwords


def test_good_passwords():
    assert validate_password(GOOD_PASSWORD) == GOOD_PASSWORD
    assert validate_password("A" * 60 + "a1" * 30) == "A" * 60 + "a1" * 30
    assert validate_password("Correct Horse 9!") == "Correct Horse 9!"
    assert validate_password("Żółć-Gęślą-7x") == "Żółć-Gęślą-7x"


def test_password_is_never_trimmed():
    assert validate_password("  Spaced-Out-77  ") == "  Spaced-Out-77  "


@pytest.mark.parametrize(
    ("value", "code"),
    [
        ("", "VALIDATION_REQUIRED"),
        ("Ab1", "VALIDATION_PASSWORD_TOO_SHORT"),
        ("Aa1" + "x" * 126, "VALIDATION_PASSWORD_TOO_LONG"),
        ("Harbor\x00Lantern1", "VALIDATION_CONTROL_CHARS"),
        ("harbor-lantern-42", "VALIDATION_PASSWORD_NEEDS_MIXED_CASE"),
        ("HARBOR-LANTERN-42", "VALIDATION_PASSWORD_NEEDS_MIXED_CASE"),
        ("Harbor-Lantern", "VALIDATION_PASSWORD_NEEDS_DIGIT"),
        ("Password123!", "VALIDATION_PASSWORD_TOO_COMMON"),
        ("Qwerty2026", "VALIDATION_PASSWORD_TOO_COMMON"),
        ("Nudge2026!!", "VALIDATION_PASSWORD_TOO_COMMON"),
        ("Abcd1234", "VALIDATION_PASSWORD_TOO_COMMON"),
        ("1234Abcd", "VALIDATION_PASSWORD_TOO_COMMON"),
    ],
)
def test_bad_passwords(value, code):
    assert code_of(validate_password, value) == code


def test_128_characters_accepted_129_refused():
    assert validate_password("Aa1" + "x" * 125)
    assert code_of(validate_password, "Aa1" + "x" * 126) == "VALIDATION_PASSWORD_TOO_LONG"


def test_password_must_not_contain_email_or_name():
    assert (
        code_of(validate_password, "Mahad-Secure-9", email="mahad@acme.co")
        == "VALIDATION_PASSWORD_CONTAINS_EMAIL"
    )
    assert (
        code_of(validate_password, "Baloch-Secure-9", full_name="Mahad Baloch")
        == "VALIDATION_PASSWORD_CONTAINS_NAME"
    )
    assert validate_password(
        "Abc-Secure-9x", email="abc@acme.co"
    )  # local part shorter than 4 is ignored


def test_password_must_differ_from_current():
    assert (
        code_of(validate_password, GOOD_PASSWORD, current=GOOD_PASSWORD)
        == "VALIDATION_PASSWORD_SAME_AS_CURRENT"
    )


def test_injected_common_list():
    assert (
        code_of(validate_password, "Zebracorn77!", common={"zebracorn"})
        == "VALIDATION_PASSWORD_TOO_COMMON"
    )
    assert validate_password(
        "Zebracorn7x", common={"zebracorn"}
    )  # only trailing digits and symbols are dropped


def test_login_password_has_no_composition_rules():
    assert validate_login_password("short") == "short"
    assert code_of(validate_login_password, "") == "VALIDATION_REQUIRED"
    assert code_of(validate_login_password, "x" * 129) == "VALIDATION_PASSWORD_TOO_LONG"


# ---- code, reset token, time zone, choices, uuid, bool


def test_code():
    assert validate_code("246810") == "246810"
    for bad in ["24681", "2468100", "24681a", "٢٤٦٨١٠", 246810, " 246810"]:
        assert code_of(validate_code, bad) == "VALIDATION_CODE_FORMAT"


def test_reset_token_format():
    assert is_reset_token_format("Mg-abc_123-xyz")
    for bad in ["abc", "a" * 201, "has space1", "a.b.c.d", None, 1234]:
        assert not is_reset_token_format(bad)


def test_timezone():
    assert validate_timezone("Asia/Karachi") == "Asia/Karachi"
    assert validate_timezone("America/New_York") == "America/New_York"
    assert validate_timezone("UTC") == "UTC"
    for bad in ["Mars/Base", "asia/karachi", "Asia/Karachi; drop"]:
        assert code_of(validate_timezone, bad) == "VALIDATION_TIMEZONE_INVALID"


def test_account_type_lowercase_only():
    assert validate_account_type("business") is AccountType.BUSINESS
    assert validate_account_type("individual") is AccountType.INDIVIDUAL
    for bad in ["Business", "Individual", "team", 2]:
        assert code_of(validate_account_type, bad) == "VALIDATION_CHOICE_INVALID"


def test_company_rules_follow_the_account_type():
    assert validate_company_for_type("  Acme   Sales ", AccountType.BUSINESS) == "Acme Sales"
    assert code_of(validate_company_for_type, None, AccountType.BUSINESS) == "VALIDATION_REQUIRED"
    assert code_of(validate_company_for_type, "A", AccountType.BUSINESS) == "VALIDATION_TOO_SHORT"
    assert (
        code_of(validate_company_for_type, "x" * 121, AccountType.BUSINESS) == "VALIDATION_TOO_LONG"
    )
    assert validate_company_for_type(None, AccountType.INDIVIDUAL) is None
    assert validate_company_for_type("  ", AccountType.INDIVIDUAL) is None
    assert (
        code_of(validate_company_for_type, "Acme", AccountType.INDIVIDUAL)
        == "VALIDATION_COMPANY_NOT_ALLOWED"
    )


def test_uuid_and_bool():
    value = "01a19be3-8259-7cb7-ae0e-6158c9870a6c"
    assert validate_uuid(value) == uuid.UUID(value)
    assert code_of(validate_uuid, "not-a-uuid") == "VALIDATION_UUID_INVALID"
    assert validate_bool(True) is True
    assert code_of(validate_bool, "true") == "VALIDATION_INVALID_TYPE"
    assert code_of(validate_bool, None) == "VALIDATION_REQUIRED"


# ---- FieldErrors: all failing fields reported together


def test_field_errors_collects_every_failure_and_raises_once():
    from common.errors import ValidationFailed
    from common.validators import FieldErrors

    errors = FieldErrors()
    assert errors.check("email", validate_email, "nope") is None
    assert errors.check("name", validate_person_name, "A") is None
    assert errors.check("code", validate_code, "123456") == "123456"
    assert errors.has_errors()
    with pytest.raises(ValidationFailed) as info:
        errors.raise_if_any()
    assert {
        name: [i.message.name for i in issues] for name, issues in info.value.fields.items()
    } == {
        "email": ["VALIDATION_EMAIL_INVALID"],
        "name": ["VALIDATION_TOO_SHORT"],
    }


def test_field_errors_does_nothing_when_everything_is_valid():
    from common.validators import FieldErrors

    errors = FieldErrors()
    assert errors.check("email", validate_email, "a@b.co") == "a@b.co"
    errors.raise_if_any()
    assert not errors.has_errors()


def test_field_errors_passes_keyword_arguments_through():
    from common.validators import FieldErrors

    errors = FieldErrors()
    assert errors.check(
        "password", validate_password, "Harbor-Lantern-42", email="x@y.co", full_name="Ali Raza"
    )
    assert (
        errors.check("password", validate_password, "Raza-Lantern-42", full_name="Ali Raza") is None
    )
