"""Format rules for contact input. Never touches the database. Returns values keyed by column name;
only the fields that were sent."""

from datetime import datetime
from typing import cast

from apps.crm.domain.enums import VISIBILITY_BY_WIRE
from common.constants import Limits
from common.errors import InvalidValue
from common.messages import Messages
from common.validators import (
    FieldErrors,
    validate_choice,
    validate_email,
    validate_name,
    validate_optional_text,
    validate_phone,
    validate_uuid,
)


def _first_name(raw: object) -> str:
    return validate_name(raw, min_len=1, max_len=Limits.PERSON_NAME_PART, require_letter=True)


def _last_name(raw: object) -> str | None:
    if raw is None or raw == "":
        return None
    return validate_name(raw, min_len=1, max_len=Limits.PERSON_NAME_PART, require_letter=True)


def _phone(raw: object) -> str | None:
    return None if raw is None or raw == "" else validate_phone(raw)


def _title(raw: object) -> str | None:
    return validate_optional_text(raw, max_len=Limits.JOB_TITLE)


def _optional_uuid(raw: object) -> object:
    return None if raw is None else validate_uuid(raw)


def _updated_at(raw: object) -> datetime:
    if raw is None or raw == "":
        raise InvalidValue(Messages.VALIDATION_REQUIRED)
    if not isinstance(raw, str):
        raise InvalidValue(Messages.VALIDATION_INVALID_TYPE)
    try:
        value = datetime.fromisoformat(raw)
    except ValueError:
        raise InvalidValue(Messages.VALIDATION_DATETIME_INVALID) from None
    if value.tzinfo is None:
        raise InvalidValue(Messages.VALIDATION_DATETIME_INVALID)
    return value


# field in the request -> (column name, rule)
_RULES = {
    "first_name": ("first_name", _first_name),
    "last_name": ("last_name", _last_name),
    "email": ("email", validate_email),
    "phone": ("phone", _phone),
    "title": ("job_title", _title),
    "company_id": ("company_id", _optional_uuid),
    "owner_id": ("owner_id", validate_uuid),
    "visibility": ("visibility", lambda raw: validate_choice(raw, VISIBILITY_BY_WIRE)),
    "team_id": ("team_id", _optional_uuid),
}


def _fields(errors: FieldErrors, sent: dict[str, object]) -> dict[str, object]:
    values: dict[str, object] = {}
    for field, (column, rule) in _RULES.items():
        if field in sent:
            values[column] = errors.check(field, rule, sent[field])
    return values


class ContactValidator:
    def validate_create(self, sent: dict[str, object]) -> dict[str, object]:
        """first_name and email are required for a contact added by hand (Q-14)."""
        errors = FieldErrors()
        values = _fields(errors, sent)
        for required, rule in (("first_name", _first_name), ("email", validate_email)):
            if required not in sent:
                errors.check(required, rule, None)
        errors.raise_if_any()
        return values

    def validate_update(self, sent: dict[str, object]) -> tuple[datetime, dict[str, object]]:
        errors = FieldErrors()
        updated_at = errors.check("updated_at", _updated_at, sent.get("updated_at"))
        values = _fields(errors, sent)
        errors.raise_if_any()
        return cast(datetime, updated_at), values
