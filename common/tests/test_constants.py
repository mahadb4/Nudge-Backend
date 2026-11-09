import hashlib
import re
import uuid

import pytest

from common.constants import (
    ACCOUNT_TYPE_BY_WIRE,
    ACCOUNT_TYPE_WIRE,
    ROLE_WIRE,
    AccountType,
    AttemptLimits,
    AuditAction,
    Limits,
    Role,
    Ttl,
    attempt_key,
    email_subject,
    ip_subject,
    user_subject,
    verify_code_key,
    verify_tries_key,
)

AUDIT_ACTION_FORMAT = re.compile(r"[a-z_]+\.[a-z_]+")  # same as the audit_logs CHECK


def test_lifetimes_match_the_decisions():
    assert Ttl.ACCESS_TOKEN == 600
    assert Ttl.REFRESH_REMEMBER == 30 * 86400
    assert Ttl.REFRESH_SESSION == 86400
    assert Ttl.VERIFY_CODE == 600
    assert Ttl.RESET_LINK == 3600


def test_roles_match_the_schema_codes():
    assert [r.value for r in Role] == [1, 2, 3, 4]
    assert set(ROLE_WIRE) == set(Role)


def test_account_types_are_lowercase_on_the_wire():
    assert ACCOUNT_TYPE_WIRE[AccountType.INDIVIDUAL] == "individual"
    assert ACCOUNT_TYPE_WIRE[AccountType.BUSINESS] == "business"
    assert ACCOUNT_TYPE_BY_WIRE["business"] is AccountType.BUSINESS
    assert "Business" not in ACCOUNT_TYPE_BY_WIRE


@pytest.mark.parametrize("action", list(AuditAction))
def test_audit_actions_pass_the_database_check(action):
    assert AUDIT_ACTION_FORMAT.fullmatch(action.value)
    assert len(action.value) <= 60


def test_attempt_limits_are_positive_and_named_uniquely():
    limits = [v for k, v in vars(AttemptLimits).items() if not k.startswith("_")]
    assert len({limit.name for limit in limits}) == len(limits)
    assert all(limit.max_attempts > 0 and limit.window_seconds > 0 for limit in limits)


DIGEST = hashlib.sha256(b"x").hexdigest()


def test_key_functions_are_deterministic():
    user_id = uuid.UUID("01a19be3-8259-7cb7-ae0e-6158c9870a6c")
    assert verify_code_key(DIGEST) == verify_code_key(DIGEST) == f"nudge:verify_code:{DIGEST}"
    assert verify_tries_key(DIGEST) == f"nudge:verify_tries:{DIGEST}"
    assert (
        attempt_key(AttemptLimits.LOGIN_IP, ip_subject("127.0.0.1"), 7)
        == "nudge:attempts:login_ip:ip:127.0.0.1:7"
    )
    assert user_subject(user_id) == f"user:{user_id}"


def test_email_keys_take_a_hash_never_an_address():
    assert email_subject(DIGEST) == f"email:{DIGEST}"
    for function in (email_subject, verify_code_key, verify_tries_key):
        with pytest.raises(ValueError):
            function("someone@example.com")


def test_the_page_size_cap_is_100():
    assert Limits.PAGE_SIZE_MAX == 100 and Limits.PAGE_SIZE_DEFAULT <= Limits.PAGE_SIZE_MAX
