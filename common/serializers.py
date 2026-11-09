"""Strict request serializers: unknown fields are refused, and values arrive untouched for the
validators."""

from collections.abc import Mapping
from typing import Any

from rest_framework import serializers
from rest_framework.exceptions import ErrorDetail

from common.constants import SAFE_FIELD_NAME

NON_FIELD = "non_field_errors"
CODE_UNKNOWN_FIELD = "unknown_field"
CODE_INVALID = "invalid"


def raw_field(source: str | None = None) -> serializers.JSONField:
    """Accepts any JSON value (or nothing). Type and format rules belong to the validators, not to
    DRF."""
    return serializers.JSONField(required=False, allow_null=True, source=source)


class StrictSerializer(serializers.Serializer):  # type: ignore[type-arg]
    def to_internal_value(self, data: Any) -> Any:
        if not isinstance(data, Mapping):
            raise serializers.ValidationError(
                {NON_FIELD: [ErrorDetail("not an object", code=CODE_INVALID)]}
            )
        unknown = [key for key in data if key not in self.fields]
        if unknown:
            # Echo a field name only if it is a plain identifier; anything else is reported without
            # its name.
            raise serializers.ValidationError(
                {
                    (str(key) if SAFE_FIELD_NAME.fullmatch(str(key)) else NON_FIELD): [
                        ErrorDetail("unknown field", code=CODE_UNKNOWN_FIELD)
                    ]
                    for key in unknown
                }
            )
        return super().to_internal_value(data)

    @classmethod
    def read_sent(cls, data: Any) -> dict[str, object]:
        """Only the fields the client actually sent (an explicit null counts as sent). For PATCH."""
        serializer = cls(data=data)
        serializer.is_valid(raise_exception=True)
        return {
            field.source: serializer.validated_data[field.source]
            for field in serializer.fields.values()
            if field.source in serializer.validated_data
        }

    @classmethod
    def read(cls, data: Any) -> dict[str, object]:
        """Every declared field as a key (None when the client sent nothing). Unknown fields raise a
        400."""
        serializer = cls(data=data)
        serializer.is_valid(raise_exception=True)
        return {
            field.source: serializer.validated_data.get(field.source)
            for field in serializer.fields.values()
        }
