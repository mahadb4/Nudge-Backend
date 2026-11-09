"""VerificationService (verify and resend), SessionService, MeService and the code store, with
fakes."""

from dataclasses import replace
from datetime import timedelta
from uuid import UUID

import pytest

from apps.accounts.domain.enums import CodeCheck
from apps.accounts.tests.fakes import AccountsWorld
from common.constants import AccountType, ActorType, AttemptLimits, AuditAction, Role, Ttl
from common.errors import NotFound, RateLimited, ValidationFailed
from common.security.refresh_tokens import sha256_hex, split_refresh_value

EMAIL = "ali@example.com"


@pytest.fixture
def world() -> AccountsWorld:
    w = AccountsWorld()
    w.register()
    w.clock.advance(31)  # past the 30 second resend window, as a real person would be
    return w


def verify(world: AccountsWorld, code: str, email: str = EMAIL, ip: str | None = "203.0.113.9"):
    return world.verification.verify(email=email, code=code, ip_address=ip)


def wrong(world: AccountsWorld) -> str:
    return "000000" if world.last_code() != "000000" else "111111"


def reject(world: AccountsWorld, code: str, email: str = EMAIL) -> str:
    with pytest.raises((ValidationFailed, RateLimited)) as info:
        verify(world, code, email)
    return info.value.code


# ---- a right code


def test_the_right_code_verifies_the_email_and_signs_the_user_in(world):
    result = verify(world, world.last_code())
    (user,) = world.users.rows.values()
    assert user.email_verified_at == world.clock.now()
    assert result.me.user.id == user.id and result.me.user.email_verified_at is not None
    assert result.me.current.organization.account_type is AccountType.BUSINESS
    assert result.me.current.membership.role is Role.OWNER


def test_the_session_holds_only_a_hash_of_the_refresh_value(world):
    result = verify(world, world.last_code())
    (session,) = world.sessions.rows.values()
    assert split_refresh_value(result.tokens.refresh_value) == session.id
    assert session.refresh_token_hash == sha256_hex(result.tokens.refresh_value)
    assert result.tokens.refresh_value not in str(session)
    assert session.ip_address == "203.0.113.9" and session.revoked_at is None


def test_the_session_lasts_one_day_and_the_cookie_is_a_session_cookie(world):
    result = verify(world, world.last_code())
    (session,) = world.sessions.rows.values()
    assert result.tokens.cookie_max_age is None
    assert session.expires_at == world.clock.now() + timedelta(days=1)


def test_the_access_token_names_the_user_and_the_session(world):
    result = verify(world, world.last_code())
    (user,), (session,) = world.users.rows.values(), world.sessions.rows.values()
    claims = world.signer.verify_access(result.tokens.access_token, now=world.clock.now())
    assert (claims.user_id, claims.session_id) == (user.id, session.id)


def test_a_code_works_only_once(world):
    code = world.last_code()
    verify(world, code)
    assert reject(world, code) == "AUTH_INVALID_CODE"


def test_verifying_writes_an_audit_row_in_the_users_organization(world):
    verify(world, world.last_code())
    event = world.audit.events[-1]
    (user,), (organization,) = world.users.rows.values(), world.organizations.rows.values()
    assert (event.action, event.actor_type, event.actor_id, event.organization_id) == (
        AuditAction.USER_EMAIL_VERIFY,
        ActorType.USER,
        user.id,
        organization.id,
    )


def test_verify_runs_in_one_transaction(world):
    opened = world.uow.opened
    verify(world, world.last_code())
    assert world.uow.opened == opened + 1


def test_the_email_may_be_typed_in_any_case(world):
    verify(world, world.last_code(), email="  ALI@Example.com ")


# ---- a wrong code


def test_a_wrong_code_is_a_400_with_one_fixed_message(world):
    with pytest.raises(ValidationFailed) as info:
        verify(world, wrong(world))
    assert info.value.code == "AUTH_INVALID_CODE" and not info.value.fields


def test_a_wrong_code_signs_nobody_in(world):
    reject(world, wrong(world))
    assert not world.sessions.rows and world.users.get_by_email(EMAIL).email_verified_at is None


def test_an_expired_code_looks_like_a_wrong_one(world):
    code = world.last_code()
    world.clock.advance(601)
    assert reject(world, code) == "AUTH_INVALID_CODE"


def test_five_wrong_tries_lock_the_code_even_for_the_right_one(world):
    code, bad = world.last_code(), wrong(world)
    for _ in range(5):
        with pytest.raises(ValidationFailed) as info:
            verify(world, bad)
        assert info.value.code == "AUTH_INVALID_CODE"
    with pytest.raises(RateLimited) as info:
        verify(world, code)
    assert info.value.code == "AUTH_CODE_ATTEMPTS_EXCEEDED" and info.value.headers == {
        "Retry-After": "30"
    }
    assert not world.sessions.rows


def test_a_new_code_lifts_the_lock(world):
    bad = wrong(world)
    for _ in range(5):
        reject(world, bad)
    world.verification.resend(email=EMAIL, ip_address="203.0.113.9")
    verify(world, world.last_code())


def test_an_unknown_email_behaves_exactly_like_a_known_one(world):
    """The same error five times, then the same lock: nothing tells the two apart."""
    bad = wrong(world)
    known = [reject(world, bad, EMAIL) for _ in range(6)]
    unknown = [reject(world, bad, "nobody@example.com") for _ in range(6)]
    assert known == unknown == ["AUTH_INVALID_CODE"] * 5 + ["AUTH_CODE_ATTEMPTS_EXCEEDED"]


def test_a_badly_formed_code_is_a_field_error(world):
    with pytest.raises(ValidationFailed) as info:
        verify(world, "12345")
    assert {n: [i.message.name for i in v] for n, v in info.value.fields.items()} == {
        "code": ["VALIDATION_CODE_FORMAT"]
    }


def test_a_bad_email_and_a_bad_code_are_reported_together(world):
    with pytest.raises(ValidationFailed) as info:
        verify(world, "abc", email="nope")
    assert set(info.value.fields) == {"email", "code"}


def test_an_inactive_user_cannot_verify(world):
    (user,) = world.users.rows.values()
    world.users.rows[user.id] = replace(user, is_active=False)
    assert reject(world, world.last_code()) == "AUTH_INVALID_CODE"


def test_twenty_one_attempts_from_one_ip_in_a_minute_are_limited(world):
    for _ in range(20):
        world.limiter.hit(AttemptLimits.VERIFY_IP, "ip:203.0.113.9")
    assert reject(world, world.last_code()) == "COMMON_RATE_LIMITED"


# ---- resend


def test_resend_sends_a_new_code_and_the_old_one_stops_working(world):
    old = world.last_code()
    world.verification.resend(email=EMAIL, ip_address=None)
    new = world.last_code()
    assert len(world.email.outbox) == 2
    if new != old:  # the 1-in-a-million case of an identical code cannot test "old stops working"
        assert reject(world, old) == "AUTH_INVALID_CODE"
    verify(world, new)


def test_resend_within_30_seconds_is_refused(world):
    world.verification.resend(email=EMAIL, ip_address=None)
    with pytest.raises(RateLimited):
        world.verification.resend(email=EMAIL, ip_address=None)
    world.clock.advance(30)
    world.verification.resend(email=EMAIL, ip_address=None)


def test_resend_says_nothing_for_unknown_or_verified_addresses(world):
    before = len(world.email.outbox)
    assert world.verification.resend(email="nobody@example.com", ip_address=None) is None
    verify(world, world.last_code())
    world.clock.advance(31)
    assert world.verification.resend(email=EMAIL, ip_address=None) is None
    assert len(world.email.outbox) == before  # no email for either


def test_resend_applies_the_30_second_rule_to_unknown_addresses_too(world):
    world.verification.resend(email="nobody@example.com", ip_address=None)
    with pytest.raises(RateLimited):
        world.verification.resend(email="nobody@example.com", ip_address=None)


def test_resend_checks_the_email_format(world):
    with pytest.raises(ValidationFailed) as info:
        world.verification.resend(email="nope", ip_address=None)
    assert set(info.value.fields) == {"email"}


# ---- sessions and the me view


def test_two_sessions_never_share_a_refresh_value(world):
    a = world.session_service.start(
        user_id=UUID(int=1), remember=True, ip_address=None, device_name=None
    )
    b = world.session_service.start(
        user_id=UUID(int=1), remember=True, ip_address=None, device_name=None
    )
    assert a.refresh_value != b.refresh_value and a.access_token != b.access_token


def test_remember_me_gives_a_thirty_day_session(world):
    tokens = world.session_service.start(
        user_id=UUID(int=1),
        remember=True,
        ip_address="203.0.113.9",
        device_name="Chrome on Windows",
    )
    (session,) = world.sessions.rows.values()
    assert (
        tokens.cookie_max_age == Ttl.REFRESH_REMEMBER
        and session.expires_at == world.clock.now() + timedelta(days=30)
    )
    assert session.device_name == "Chrome on Windows"


def test_me_is_not_found_for_a_user_without_an_organization(world):
    with pytest.raises(NotFound):
        world.me_service.get_me(UUID(int=12345))


# ---- the code store itself


def test_the_cache_holds_only_a_hash_of_the_code(world):
    code = world.last_code()
    stored = [value for value, _ in world.cache._items.values()]
    assert code not in stored and EMAIL not in " ".join(stored)


def test_check_does_not_consume_the_code(world):
    digest = world.digests.digest("email", EMAIL)
    code = world.last_code()
    assert world.code_repository.check(digest, code) is CodeCheck.OK
    assert world.code_repository.check(digest, code) is CodeCheck.OK
    world.code_repository.discard(digest)
    assert world.code_repository.check(digest, code) is CodeCheck.WRONG
