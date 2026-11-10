"""Application errors (ARCHITECTURE 2, 4). Services raise these by Messages member; never HTTP
responses.

Framework-free: the HTTP mapping lives in common/responses.py.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from http import HTTPStatus
from typing import ClassVar

from common.constants import Header
from common.messages import Messages


@dataclass(frozen=True, slots=True)
class FieldIssue:
    message: Messages
    values: tuple[object, ...] = ()

    def render(self) -> str:
        return self.message.render(*self.values)


class InvalidValue(Exception):
    """Raised by validators. The API layer collects these into one ValidationFailed."""

    def __init__(self, message: Messages, *values: object) -> None:
        super().__init__(message.name)
        self.issue = FieldIssue(message, values)


class AppError(Exception):
    status: ClassVar[HTTPStatus] = HTTPStatus.INTERNAL_SERVER_ERROR
    default_message: ClassVar[Messages | None] = Messages.COMMON_SERVER_ERROR

    def __init__(
        self,
        message: Messages | None = None,
        *values: object,
        fields: Mapping[str, Sequence[FieldIssue]] | None = None,
        current: Mapping[str, object] | None = None,
        headers: Mapping[str, str] | None = None,
        extra: Mapping[str, object] | None = None,
    ) -> None:
        chosen = message or self.default_message
        if chosen is None:
            raise TypeError(f"{type(self).__name__} needs a message")
        super().__init__(chosen.name)
        self.message = chosen
        self.values = values
        self.fields = {name: tuple(issues) for name, issues in (fields or {}).items()}
        self.current = current
        self.headers = dict(headers or {})
        # More keys for the reply body (for example "existing"); never code, detail or fields.
        self.extra = dict(extra or {})

    @property
    def code(self) -> str:
        return self.message.name

    @property
    def detail(self) -> str:
        return self.message.render(*self.values)


class ValidationFailed(AppError):
    status = HTTPStatus.BAD_REQUEST
    default_message = Messages.COMMON_VALIDATION_FAILED

    @classmethod
    def from_issues(cls, issues: Mapping[str, Sequence[FieldIssue]]) -> "ValidationFailed":
        return cls(fields=issues)

    @classmethod
    def for_field(cls, name: str, message: Messages, *values: object) -> "ValidationFailed":
        return cls(fields={name: [FieldIssue(message, values)]})


class Unauthorized(AppError):
    status = HTTPStatus.UNAUTHORIZED
    default_message = Messages.AUTH_ACCESS_TOKEN_INVALID


class Forbidden(AppError):
    status = HTTPStatus.FORBIDDEN
    default_message = Messages.COMMON_FORBIDDEN


class NotFound(AppError):
    status = HTTPStatus.NOT_FOUND
    default_message = Messages.COMMON_NOT_FOUND


class MethodNotAllowed(AppError):
    status = HTTPStatus.METHOD_NOT_ALLOWED
    default_message = Messages.COMMON_METHOD_NOT_ALLOWED


class Conflict(AppError):
    status = HTTPStatus.CONFLICT
    default_message = None  # every conflict names its own message


class RateLimited(AppError):
    status = HTTPStatus.TOO_MANY_REQUESTS
    default_message = Messages.COMMON_RATE_LIMITED

    def __init__(self, message: Messages | None = None, *, retry_after: int) -> None:
        super().__init__(message, headers={Header.RETRY_AFTER: str(max(1, int(retry_after)))})
        self.retry_after = max(1, int(retry_after))


class ServiceUnavailable(AppError):
    status = HTTPStatus.SERVICE_UNAVAILABLE
    default_message = Messages.COMMON_SERVICE_UNAVAILABLE
