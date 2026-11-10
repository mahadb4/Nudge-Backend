"""Field rules shared by every module (port of the frontend's validate.ts, plus the validation
spec).

Each function returns the normalised value or raises InvalidValue(message, **params).
Framework-free.
Where the frontend and the database column disagree, the frontend limit wins (Q-30).
"""

import re
from collections.abc import Callable, Container, Mapping
from datetime import time
from functools import lru_cache
from typing import TypeVar
from uuid import UUID
from zoneinfo import available_timezones

import phonenumbers

from common.constants import ACCOUNT_TYPE_BY_WIRE, AccountType, AuthRules, Limits
from common.errors import FieldIssue, InvalidValue, ValidationFailed
from common.messages import Messages
from common.text import clean, contains_markup, has_control_chars, has_letter, strip_invisible

T = TypeVar("T")

_EMAIL = re.compile(
    r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+",
    re.IGNORECASE | re.ASCII,
)
_TLD_LETTERS = re.compile(r"\.[a-z]{2,}$", re.IGNORECASE | re.ASCII)
_CODE = re.compile(rf"[0-9]{{{AuthRules.CODE_LENGTH}}}")
_RESET_TOKEN = re.compile(rf"[A-Za-z0-9_-]{{{Limits.RESET_TOKEN_MIN},{Limits.RESET_TOKEN_MAX}}}")
_PASSWORD_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_TRAILING_DIGITS_SYMBOLS = re.compile(r"[\d\W_]+$", re.ASCII)
_REPEATED = re.compile(r"(.)\1+", re.DOTALL)
_SEQUENCE_START = re.compile(r"(?:0123|1234|2345|3456|abcd)")
_SEQUENCE_MAX_LEN = 10
_NAME_TOKEN_MIN = 4

# The frontend's common-password list, compared after dropping trailing digits and symbols.
FRONTEND_COMMON_PASSWORDS = frozenset(
    {
        "password",
        "passw0rd",
        "qwerty",
        "qwertyui",
        "qwertyuiop",
        "letmein",
        "welcome",
        "admin",
        "administrator",
        "iloveyou",
        "monkey",
        "dragon",
        "football",
        "baseball",
        "trustno",
        "changeme",
        "abcdefgh",
        "abc",
        "login",
        "master",
        "sunshine",
        "princess",
        "nudge",
        "nudge2026",
        "acme",
        "test",
        "testing",
    }
)


_DOMAIN = re.compile(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}", re.ASCII)
_TIME_OF_DAY = re.compile(r"([0-9]{2}):([0-9]{2})")


def _required_text(raw: object) -> str:
    if raw is None or raw == "":
        raise InvalidValue(Messages.VALIDATION_REQUIRED)
    if not isinstance(raw, str):
        raise InvalidValue(Messages.VALIDATION_INVALID_TYPE)
    if has_control_chars(raw):
        raise InvalidValue(Messages.VALIDATION_CONTROL_CHARS)
    return raw


def normalize_email(raw: str) -> str:
    return strip_invisible(raw).strip().lower()


def validate_email(raw: object) -> str:
    email = normalize_email(_required_text(raw))
    if not email:
        raise InvalidValue(Messages.VALIDATION_REQUIRED)
    if len(email) > Limits.EMAIL:
        raise InvalidValue(Messages.VALIDATION_TOO_LONG, Limits.EMAIL)
    local = email.split("@", 1)[0]
    if (
        ".." in email
        or email.startswith(".")
        or len(local) > Limits.EMAIL_LOCAL
        or local.endswith(".")
        or not _EMAIL.fullmatch(email)
        or not _TLD_LETTERS.search(email)
    ):
        raise InvalidValue(Messages.VALIDATION_EMAIL_INVALID)
    return email


def validate_name(raw: object, *, min_len: int, max_len: int, require_letter: bool = False) -> str:
    value = clean(_required_text(raw))
    if not value:
        raise InvalidValue(Messages.VALIDATION_REQUIRED)
    if len(value) < min_len:
        raise InvalidValue(Messages.VALIDATION_TOO_SHORT, min_len)
    if len(value) > max_len:
        raise InvalidValue(Messages.VALIDATION_TOO_LONG, max_len)
    if contains_markup(value):
        raise InvalidValue(Messages.VALIDATION_MARKUP_NOT_ALLOWED)
    if require_letter and not has_letter(value):
        raise InvalidValue(Messages.VALIDATION_NAME_NEEDS_LETTER)
    return value


def validate_person_name(raw: object) -> str:
    return validate_name(raw, min_len=Limits.NAME_MIN, max_len=Limits.NAME, require_letter=True)


def validate_company_name(raw: object) -> str:
    return validate_name(raw, min_len=Limits.COMPANY_MIN, max_len=Limits.COMPANY)


def validate_domain(raw: object) -> str:
    """A lower-case host name with at least one dot. A URL is refused, not trimmed (Q-16)."""
    value = _required_text(raw).strip().lower()
    if len(value) > Limits.DOMAIN or not _DOMAIN.fullmatch(value):
        raise InvalidValue(Messages.VALIDATION_DOMAIN_INVALID)
    return value


def validate_optional_text(raw: object, *, max_len: int) -> str | None:
    """Free text that may be empty: null or blank means "none"."""
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise InvalidValue(Messages.VALIDATION_INVALID_TYPE)
    if has_control_chars(raw):
        raise InvalidValue(Messages.VALIDATION_CONTROL_CHARS)
    value = clean(raw)
    if len(value) > max_len:
        raise InvalidValue(Messages.VALIDATION_TOO_LONG, max_len)
    return value or None


def validate_phone(raw: object) -> str:
    """International format with '+' and the country code, normalised to E.164 (Q-12)."""
    value = _required_text(raw).strip()
    if not value.startswith("+"):
        raise InvalidValue(Messages.VALIDATION_PHONE_NEEDS_PLUS)
    try:
        number = phonenumbers.parse(value, None)
    except phonenumbers.NumberParseException:
        raise InvalidValue(Messages.VALIDATION_PHONE_INVALID) from None
    if not phonenumbers.is_valid_number(number):
        raise InvalidValue(Messages.VALIDATION_PHONE_INVALID)
    return phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)


def validate_time_of_day(raw: object) -> time:
    """'HH:MM' on a 24 hour clock."""
    value = _required_text(raw).strip()
    match = _TIME_OF_DAY.fullmatch(value)
    if match is None:
        raise InvalidValue(Messages.VALIDATION_TIME_INVALID)
    hour, minute = int(match.group(1)), int(match.group(2))
    if hour > 23 or minute > 59:
        raise InvalidValue(Messages.VALIDATION_TIME_INVALID)
    return time(hour, minute)


def validate_password(
    raw: object,
    *,
    email: str | None = None,
    full_name: str | None = None,
    current: str | None = None,
    common: Container[str] = FRONTEND_COMMON_PASSWORDS,
) -> str:
    """Rules for a new password. The value is never trimmed, cleaned or lowercased."""
    if raw is None or raw == "":
        raise InvalidValue(Messages.VALIDATION_REQUIRED)
    if not isinstance(raw, str):
        raise InvalidValue(Messages.VALIDATION_INVALID_TYPE)
    if len(raw) < Limits.PASSWORD_MIN:
        raise InvalidValue(Messages.VALIDATION_PASSWORD_TOO_SHORT, Limits.PASSWORD_MIN)
    if len(raw) > Limits.PASSWORD_MAX:
        raise InvalidValue(Messages.VALIDATION_PASSWORD_TOO_LONG, Limits.PASSWORD_MAX)
    if _PASSWORD_CONTROL.search(raw):
        raise InvalidValue(Messages.VALIDATION_CONTROL_CHARS)
    # ASCII classes, exactly as the frontend checks them.
    if not re.search(r"[a-z]", raw) or not re.search(r"[A-Z]", raw):
        raise InvalidValue(Messages.VALIDATION_PASSWORD_NEEDS_MIXED_CASE)
    if not re.search(r"[0-9]", raw):
        raise InvalidValue(Messages.VALIDATION_PASSWORD_NEEDS_DIGIT)
    lowered = raw.lower()
    local = (email or "").split("@", 1)[0].lower()
    if len(local) >= _NAME_TOKEN_MIN and local in lowered:
        raise InvalidValue(Messages.VALIDATION_PASSWORD_CONTAINS_EMAIL)
    tokens = [
        token
        for token in clean(full_name or "").lower().split(" ")
        if len(token) >= _NAME_TOKEN_MIN
    ]
    if any(token in lowered for token in tokens):
        raise InvalidValue(Messages.VALIDATION_PASSWORD_CONTAINS_NAME)
    if (
        _TRAILING_DIGITS_SYMBOLS.sub("", lowered) in common
        or _REPEATED.fullmatch(raw)
        or (_SEQUENCE_START.match(lowered) and len(raw) < _SEQUENCE_MAX_LEN)
    ):
        raise InvalidValue(Messages.VALIDATION_PASSWORD_TOO_COMMON)
    if current is not None and raw == current:
        raise InvalidValue(Messages.VALIDATION_PASSWORD_SAME_AS_CURRENT)
    return raw


def validate_login_password(raw: object) -> str:
    """Sign-in only: present and at most 128 characters, no composition rules (old passwords still
    work)."""
    if raw is None or raw == "":
        raise InvalidValue(Messages.VALIDATION_REQUIRED)
    if not isinstance(raw, str):
        raise InvalidValue(Messages.VALIDATION_INVALID_TYPE)
    if len(raw) > Limits.PASSWORD_MAX:
        raise InvalidValue(Messages.VALIDATION_PASSWORD_TOO_LONG, Limits.PASSWORD_MAX)
    return raw


def validate_code(raw: object) -> str:
    if raw is None or raw == "":
        raise InvalidValue(Messages.VALIDATION_REQUIRED)
    if not isinstance(raw, str) or not _CODE.fullmatch(raw):
        raise InvalidValue(Messages.VALIDATION_CODE_FORMAT)
    return raw


def is_reset_token_format(raw: object) -> bool:
    return isinstance(raw, str) and bool(_RESET_TOKEN.fullmatch(raw))


@lru_cache(maxsize=1)
def _timezones() -> frozenset[str]:
    return frozenset(available_timezones())


def validate_timezone(raw: object) -> str:
    value = _required_text(raw).strip()
    if len(value) > Limits.TIMEZONE or value not in _timezones():
        raise InvalidValue(Messages.VALIDATION_TIMEZONE_INVALID)
    return value


def validate_choice(raw: object, allowed: Mapping[str, T]) -> T:
    if raw is None or raw == "":
        raise InvalidValue(Messages.VALIDATION_REQUIRED)
    if not isinstance(raw, str) or raw not in allowed:
        raise InvalidValue(Messages.VALIDATION_CHOICE_INVALID)
    return allowed[raw]


def validate_account_type(raw: object) -> AccountType:
    """Lowercase on the wire: 'individual' or 'business'. Capitalised values are refused."""
    return validate_choice(raw, ACCOUNT_TYPE_BY_WIRE)


def validate_company_for_type(raw: object, account_type: AccountType) -> str | None:
    """Business needs a company name; Individual must send none (absent, null or empty)."""
    if account_type is AccountType.BUSINESS:
        return validate_company_name(raw)
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None
    raise InvalidValue(Messages.VALIDATION_COMPANY_NOT_ALLOWED)


def validate_uuid(raw: object) -> UUID:
    if raw is None or raw == "":
        raise InvalidValue(Messages.VALIDATION_REQUIRED)
    if not isinstance(raw, str):
        raise InvalidValue(Messages.VALIDATION_UUID_INVALID)
    try:
        return UUID(raw)
    except ValueError:
        raise InvalidValue(Messages.VALIDATION_UUID_INVALID) from None


def validate_bool(raw: object) -> bool:
    """JSON true or false only; strings like 'true' are refused."""
    if raw is None:
        raise InvalidValue(Messages.VALIDATION_REQUIRED)
    if not isinstance(raw, bool):
        raise InvalidValue(Messages.VALIDATION_INVALID_TYPE)
    return raw


class FieldErrors:
    """Runs several validators and reports every failing field at once, as one ValidationFailed."""

    def __init__(self) -> None:
        self._issues: dict[str, list[FieldIssue]] = {}

    def check(
        self, field: str, validate: Callable[..., T], *args: object, **kwargs: object
    ) -> T | None:
        try:
            return validate(*args, **kwargs)
        except InvalidValue as exc:
            self._issues.setdefault(field, []).append(exc.issue)
            return None

    def has_errors(self) -> bool:
        return bool(self._issues)

    def raise_if_any(self) -> None:
        if self._issues:
            raise ValidationFailed.from_issues(self._issues)
