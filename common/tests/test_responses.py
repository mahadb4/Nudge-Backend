"""Every exception becomes {"code", "detail"} with the right status; internals never leak."""

import json

import pytest
from django.core.exceptions import RequestDataTooBig
from django.http import Http404
from django.test import RequestFactory
from rest_framework import exceptions as drf
from rest_framework import serializers

from common.errors import FieldIssue, RateLimited, Unauthorized, ValidationFailed
from common.messages import Messages
from common.responses import (
    _DRF_FIELD_CODES,
    accepted,
    exception_handler,
    json_bad_request,
    json_csrf_failure,
    json_not_found,
    json_server_error,
)


def handle(exc):
    response = exception_handler(exc, {"view": None})
    return response.status_code, response.data, response


@pytest.mark.parametrize(
    ("exc", "status", "code"),
    [
        (drf.ParseError(), 400, "COMMON_MALFORMED_JSON"),
        (drf.UnsupportedMediaType("text/plain"), 400, "COMMON_INVALID_CONTENT_TYPE"),
        (RequestDataTooBig(), 400, "COMMON_BODY_TOO_LARGE"),
        (drf.NotAuthenticated(), 401, "AUTH_ACCESS_TOKEN_INVALID"),
        (drf.AuthenticationFailed(), 401, "AUTH_ACCESS_TOKEN_INVALID"),
        (drf.PermissionDenied(), 403, "COMMON_FORBIDDEN"),
        (drf.NotFound(), 404, "COMMON_NOT_FOUND"),
        (Http404(), 404, "COMMON_NOT_FOUND"),
        (drf.MethodNotAllowed("DELETE"), 405, "COMMON_METHOD_NOT_ALLOWED"),
        (drf.Throttled(wait=12.3), 429, "COMMON_RATE_LIMITED"),
    ],
)
def test_framework_exceptions_are_mapped(exc, status, code):
    got_status, body, _ = handle(exc)
    assert (got_status, body["code"]) == (status, code)
    assert body["detail"] == Messages[code].value


def test_app_error_body_and_headers():
    status, body, response = handle(RateLimited(retry_after=30))
    assert status == 429
    assert body == {"code": "COMMON_RATE_LIMITED", "detail": Messages.COMMON_RATE_LIMITED.value}
    assert response["Retry-After"] == "30"
    assert response["Cache-Control"] == "no-store"


def test_app_error_with_explicit_message():
    status, body, _ = handle(Unauthorized(Messages.AUTH_BAD_CREDENTIALS))
    assert status == 401 and body["code"] == "AUTH_BAD_CREDENTIALS"


def test_validation_failed_lists_fields_with_codes_and_texts():
    err = ValidationFailed.from_issues(
        {
            "email": [FieldIssue(Messages.VALIDATION_EMAIL_INVALID)],
            "name": [FieldIssue(Messages.VALIDATION_TOO_LONG, (80,))],
        }
    )
    status, body, _ = handle(err)
    assert status == 400
    assert body["code"] == "COMMON_VALIDATION_FAILED"
    assert body["fields"] == {
        "email": [
            {"code": "VALIDATION_EMAIL_INVALID", "detail": Messages.VALIDATION_EMAIL_INVALID.value}
        ],
        "name": [{"code": "VALIDATION_TOO_LONG", "detail": "Use at most 80 characters."}],
    }


class Sample(serializers.Serializer):
    email = serializers.CharField(max_length=5)
    remember = serializers.BooleanField()
    nested = serializers.DictField(child=serializers.IntegerField())
    short = serializers.CharField(min_length=3)


def test_drf_serializer_errors_become_field_codes():
    s = Sample(data={"email": "toolong", "nested": {"a": "x"}, "short": "a"})
    assert not s.is_valid()
    status, body, _ = handle(drf.ValidationError(s.errors))
    assert status == 400
    assert body["fields"]["email"][0]["code"] == "VALIDATION_VALUE_TOO_LONG"
    assert body["fields"]["short"][0]["code"] == "VALIDATION_VALUE_TOO_SHORT"
    assert body["fields"]["remember"][0]["code"] == "VALIDATION_REQUIRED"
    assert body["fields"]["nested.a"][0]["code"] == "VALIDATION_INVALID_TYPE"


def test_drf_fallback_messages_have_no_placeholders():
    """DRF does not tell us the limit, so these messages must read well without a number."""
    for message in {*_DRF_FIELD_CODES.values(), Messages.VALIDATION_INVALID_TYPE}:
        assert "{" not in message.value
    _, body, _ = handle(
        drf.ValidationError({"email": ["Ensure this field has no more than 5 characters."]})
    )
    details = [
        body["detail"],
        *(issue["detail"] for issues in body["fields"].values() for issue in issues),
    ]
    assert details and all("{" not in text and "}" not in text for text in details)


def test_drf_error_without_field_goes_to_non_field_errors():
    _, body, _ = handle(drf.ValidationError("nope"))
    assert list(body["fields"]) == ["non_field_errors"]


def test_unknown_exception_is_a_generic_500_with_no_leak(caplog):
    status, body, _ = handle(KeyError("SECRET-internal-detail postgres://user:pw@host"))
    assert status == 500
    assert body == {"code": "COMMON_SERVER_ERROR", "detail": Messages.COMMON_SERVER_ERROR.value}
    assert "SECRET" not in json.dumps(body)
    assert "Unhandled KeyError" in caplog.text


def test_accepted_body():
    response = accepted(Messages.AUTH_CODE_SENT)
    assert response.status_code == 202
    assert response.data == {"code": "AUTH_CODE_SENT", "detail": Messages.AUTH_CODE_SENT.value}


@pytest.mark.parametrize(
    ("view", "args", "status", "code"),
    [
        (json_bad_request, (RequestDataTooBig(),), 400, "COMMON_BODY_TOO_LARGE"),
        (json_bad_request, (None,), 400, "COMMON_VALIDATION_FAILED"),
        (json_not_found, (None,), 404, "COMMON_NOT_FOUND"),
        (json_server_error, (), 500, "COMMON_SERVER_ERROR"),
        (json_csrf_failure, ("CSRF cookie not set.",), 403, "AUTH_CSRF_FAILED"),
    ],
)
def test_django_level_handlers_are_json(view, args, status, code):
    response = view(RequestFactory().get("/x"), *args)
    body = json.loads(response.content)
    assert response.status_code == status
    assert body["code"] == code
    assert "CSRF cookie" not in response.content.decode()
    assert response["Cache-Control"] == "no-store"
