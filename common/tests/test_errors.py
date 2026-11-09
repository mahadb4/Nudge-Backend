import pytest

from common.constants import Header
from common.errors import (
    AppError,
    Conflict,
    FieldIssue,
    Forbidden,
    InvalidValue,
    MethodNotAllowed,
    NotFound,
    RateLimited,
    ServiceUnavailable,
    Unauthorized,
    ValidationFailed,
)
from common.messages import Messages


@pytest.mark.parametrize(
    ("cls", "status", "code"),
    [
        (AppError, 500, "COMMON_SERVER_ERROR"),
        (ValidationFailed, 400, "COMMON_VALIDATION_FAILED"),
        (Unauthorized, 401, "AUTH_ACCESS_TOKEN_INVALID"),
        (Forbidden, 403, "COMMON_FORBIDDEN"),
        (NotFound, 404, "COMMON_NOT_FOUND"),
        (MethodNotAllowed, 405, "COMMON_METHOD_NOT_ALLOWED"),
        (ServiceUnavailable, 503, "COMMON_SERVICE_UNAVAILABLE"),
    ],
)
def test_status_and_default_code(cls, status, code):
    err = cls()
    assert err.status == status
    assert err.code == code
    assert err.detail == Messages[code].value


def test_conflict_needs_its_own_message():
    with pytest.raises(TypeError):
        Conflict()
    assert Conflict(Messages.COMMON_FORBIDDEN).status == 409


def test_explicit_message_wins():
    err = Unauthorized(Messages.AUTH_BAD_CREDENTIALS)
    assert err.code == "AUTH_BAD_CREDENTIALS"
    assert err.detail == "That email and password do not match."


def test_values_fill_the_placeholders_in_detail():
    err = ValidationFailed(Messages.VALIDATION_TOO_LONG, 5)
    assert err.detail == "Use at most 5 characters."
    assert err.values == (5,)


def test_exception_args_are_not_overwritten():
    assert AppError(Messages.COMMON_NOT_FOUND).args == ("COMMON_NOT_FOUND",)


def test_rate_limited_sets_retry_after_header():
    err = RateLimited(retry_after=29.2)
    assert err.status == 429
    assert err.headers == {Header.RETRY_AFTER: "29"}
    assert RateLimited(retry_after=0).headers[Header.RETRY_AFTER] == "1"


def test_rate_limited_can_carry_a_specific_message():
    assert (
        RateLimited(Messages.AUTH_CODE_ATTEMPTS_EXCEEDED, retry_after=1).code
        == "AUTH_CODE_ATTEMPTS_EXCEEDED"
    )


def test_from_issues_and_for_field():
    err = ValidationFailed.from_issues({"email": [FieldIssue(Messages.VALIDATION_EMAIL_INVALID)]})
    assert err.code == "COMMON_VALIDATION_FAILED"
    assert [i.message.name for i in err.fields["email"]] == ["VALIDATION_EMAIL_INVALID"]
    one = ValidationFailed.for_field("name", Messages.VALIDATION_TOO_SHORT, 2)
    assert one.fields["name"][0].render() == "Use at least 2 characters."


def test_invalid_value_carries_an_issue():
    exc = InvalidValue(Messages.VALIDATION_TOO_LONG, 80)
    assert exc.issue.message is Messages.VALIDATION_TOO_LONG
    assert exc.issue.render() == "Use at most 80 characters."
