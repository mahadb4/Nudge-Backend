"""HTTP edge of the error model (ARCHITECTURE 4): every error body is {"code", "detail"} from
messages.py.

Used only by controllers and settings. Services raise AppError; this module turns any exception
into a
JSON response and never puts internal text, stack traces or request bodies into it.
"""

import logging
import math
from http import HTTPStatus

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.core.exceptions import RequestDataTooBig
from django.http import Http404, HttpRequest, JsonResponse
from rest_framework import exceptions as drf
from rest_framework.response import Response

from common.constants import Header, HeaderValue
from common.errors import (
    AppError,
    FieldIssue,
    Forbidden,
    MethodNotAllowed,
    NotFound,
    RateLimited,
    Unauthorized,
    ValidationFailed,
)
from common.messages import Messages

logger = logging.getLogger(__name__)

NON_FIELD = "non_field_errors"

# DRF serializer error codes -> our field codes. Anything else is an invalid type.
_DRF_FIELD_CODES = {
    "required": Messages.VALIDATION_REQUIRED,
    "null": Messages.VALIDATION_REQUIRED,
    "blank": Messages.VALIDATION_REQUIRED,
    "max_length": Messages.VALIDATION_VALUE_TOO_LONG,
    "min_length": Messages.VALIDATION_VALUE_TOO_SHORT,
    "invalid_choice": Messages.VALIDATION_CHOICE_INVALID,
    "unknown_field": Messages.VALIDATION_UNKNOWN_FIELD,
}


def error_body(err: AppError) -> dict[str, object]:
    body: dict[str, object] = {"code": err.code, "detail": err.detail}
    if err.fields:
        body["fields"] = {
            name: [{"code": issue.message.name, "detail": issue.render()} for issue in issues]
            for name, issues in err.fields.items()
        }
    if err.current is not None:
        body["current"] = err.current
    for key, value in err.extra.items():
        body.setdefault(key, value)
    return body


def error_response(err: AppError) -> Response:
    response = Response(error_body(err), status=err.status)
    for name, value in err.headers.items():
        response[name] = value
    response[Header.CACHE_CONTROL] = HeaderValue.NO_STORE
    return response


def accepted(message: Messages) -> Response:
    """202 for flows that answer the same way for every email (register, resend, reset)."""
    return Response({"code": message.name, "detail": message.render()}, status=HTTPStatus.ACCEPTED)


def _issues_from_drf(detail: object, prefix: str = "") -> dict[str, list[FieldIssue]]:
    issues: dict[str, list[FieldIssue]] = {}
    if isinstance(detail, dict):
        for name, value in detail.items():
            key = f"{prefix}.{name}" if prefix else str(name)
            for field_name, field_issues in _issues_from_drf(value, key).items():
                issues.setdefault(field_name, []).extend(field_issues)
        return issues
    items = detail if isinstance(detail, list) else [detail]
    name = prefix or NON_FIELD
    for item in items:
        if isinstance(item, (dict, list)):
            for field_name, field_issues in _issues_from_drf(item, name).items():
                issues.setdefault(field_name, []).extend(field_issues)
            continue
        code = getattr(item, "code", None)
        issues.setdefault(name, []).append(
            FieldIssue(_DRF_FIELD_CODES.get(code, Messages.VALIDATION_INVALID_TYPE))
        )
    return issues


def to_app_error(exc: Exception) -> AppError:
    if isinstance(exc, AppError):
        return exc
    if isinstance(exc, drf.ValidationError):
        return ValidationFailed.from_issues(_issues_from_drf(exc.detail))
    if isinstance(exc, drf.ParseError):
        return ValidationFailed(Messages.COMMON_MALFORMED_JSON)
    if isinstance(exc, drf.UnsupportedMediaType):
        return ValidationFailed(Messages.COMMON_INVALID_CONTENT_TYPE)
    if isinstance(exc, RequestDataTooBig):
        return ValidationFailed(Messages.COMMON_BODY_TOO_LARGE)
    if isinstance(exc, (drf.NotAuthenticated, drf.AuthenticationFailed)):
        return Unauthorized()
    if isinstance(exc, (drf.PermissionDenied, DjangoPermissionDenied)):
        return Forbidden()
    if isinstance(exc, (drf.NotFound, Http404)):
        return NotFound()
    if isinstance(exc, drf.MethodNotAllowed):
        return MethodNotAllowed()
    if isinstance(exc, drf.Throttled):
        return RateLimited(retry_after=math.ceil(exc.wait or 1))
    return AppError()


def exception_handler(exc: Exception, context: dict[str, object]) -> Response:
    """REST_FRAMEWORK['EXCEPTION_HANDLER']. Unknown exceptions are logged and answered with a
    generic 500."""
    err = to_app_error(exc)
    if err.status >= 500 and not isinstance(exc, AppError):
        view = context.get("view")
        logger.error(
            "Unhandled %s in %s",
            type(exc).__name__,
            type(view).__name__ if view else "?",
            exc_info=exc,
        )
    return error_response(err)


def _json(err: AppError) -> JsonResponse:
    response = JsonResponse(error_body(err), status=err.status)
    response[Header.CACHE_CONTROL] = HeaderValue.NO_STORE
    return response


def json_bad_request(request: HttpRequest, exception: Exception | None = None) -> JsonResponse:
    """Django handler400 (outside DRF views): an oversized body or a malformed request."""
    if isinstance(exception, RequestDataTooBig):
        return _json(ValidationFailed(Messages.COMMON_BODY_TOO_LARGE))
    return _json(ValidationFailed())


def json_forbidden(request: HttpRequest, exception: Exception | None = None) -> JsonResponse:
    return _json(Forbidden())


def json_not_found(request: HttpRequest, exception: Exception | None = None) -> JsonResponse:
    return _json(NotFound())


def json_server_error(request: HttpRequest) -> JsonResponse:
    return _json(AppError())


def json_csrf_failure(request: HttpRequest, reason: str = "") -> JsonResponse:
    """CSRF_FAILURE_VIEW for Django's CsrfViewMiddleware. The reason is never sent to the client."""
    return _json(Forbidden(Messages.AUTH_CSRF_FAILED))
