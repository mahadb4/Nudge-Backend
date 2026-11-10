"""Format rules for company input. Never touches the database. Returns values keyed by column
name; only the fields that were sent."""

from datetime import datetime
from typing import cast

from apps.crm.domain.enums import COMPANY_SIZE_BY_WIRE, VISIBILITY_BY_WIRE
from common.constants import Limits
from common.errors import InvalidValue
from common.messages import Messages
from common.validators import (
    FieldErrors,
    validate_choice,
    validate_company_name,
    validate_domain,
    validate_optional_text,
    validate_uuid,
)


def _domain(raw: object) -> str | None:
    return None if raw is None or raw == "" else validate_domain(raw)


def _industry(raw: object) -> str | None:
    return validate_optional_text(raw, max_len=Limits.INDUSTRY)


def _size_range(raw: object) -> object:
    return None if raw is None else validate_choice(raw, COMPANY_SIZE_BY_WIRE)


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
    "name": ("name", validate_company_name),
    "domain": ("domain", _domain),
    "industry": ("industry", _industry),
    "size_range": ("size_range", _size_range),
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


class CompanyValidator:
    def validate_create(self, sent: dict[str, object]) -> dict[str, object]:
        errors = FieldErrors()
        values = _fields(errors, sent)
        if "name" not in sent:
            errors.check("name", validate_company_name, None)
        errors.raise_if_any()
        return values

    def validate_update(self, sent: dict[str, object]) -> tuple[datetime, dict[str, object]]:
        """updated_at (the value the client read) is required; the rest is optional."""
        errors = FieldErrors()
        updated_at = errors.check("updated_at", _updated_at, sent.get("updated_at"))
        values = _fields(errors, sent)
        errors.raise_if_any()
        return cast(datetime, updated_at), values
