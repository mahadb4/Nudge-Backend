"""Format rules for deal stage input. Never touches the database."""

from typing import cast
from uuid import UUID

from common.constants import Limits
from common.errors import FieldIssue, InvalidValue, ValidationFailed
from common.messages import Messages
from common.validators import FieldErrors, validate_name, validate_uuid


class StageValidator:
    def validate_name(self, sent: dict[str, object]) -> str:
        errors = FieldErrors()
        name = errors.check(
            "name",
            validate_name,
            sent.get("name"),
            min_len=1,
            max_len=Limits.STAGE_NAME,
        )
        errors.raise_if_any()
        return cast(str, name)

    def validate_order(self, sent: dict[str, object]) -> list[UUID]:
        raw = sent.get("ids")
        if not isinstance(raw, list):
            message = (
                Messages.VALIDATION_REQUIRED if raw is None else Messages.VALIDATION_LIST_INVALID
            )
            raise ValidationFailed(fields={"ids": [FieldIssue(message)]})
        ids: list[UUID] = []
        for item in raw:
            try:
                ids.append(validate_uuid(item))
            except InvalidValue as exc:
                raise ValidationFailed(fields={"ids": [exc.issue]}) from None
        return ids
