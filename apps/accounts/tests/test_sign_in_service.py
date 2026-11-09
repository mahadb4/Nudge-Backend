"""SignInService (login, refresh, logout) and AuthenticationService with fakes: no database, no
HTTP."""

from dataclasses import replace
from datetime import timedelta

import pytest

from apps.accounts.domain.entities import SignInResult
from apps.accounts.tests.fakes import VALID_REGISTRATION, AccountsWorld
from common.constants import ActorType, AuditAction, Ttl
from common.errors import Forbidden, RateLimited, Unauthorized, ValidationFailed
from common.messages import Messages
from common.security.refresh_tokens import sha256_hex, split_refresh_value

EMAIL = VALID_REGISTRATION["email"]
PASSWORD = VALID_REGISTRATION["password"]
IP = "203.0.113.9"
AGENT = "Mozilla/5.0 (X11; Linux x86_64) Firefox/130.0"


@pytest.fixture
def world() -> AccountsWorld:
    w = AccountsWorld()
    w.verified_user()
    return w


def login(world: AccountsWorld, **overrides: object) -> SignInResult:
    values = dict(email=EMAIL, password=PASSWORD, remember=False, ip_address=IP, user_agent=AGENT)
    return world.sign_in.login(**{**values, **overrides})


def failing_code(call) -> str:
    with pytest.raises((Unauthorized, Forbidden, RateLimited, ValidationFailed)) as info:
        call()
    return info.value.code


def only_session(world: AccountsWorld):
    (session,) = world.sessions.rows.values()
    return session


# ---- login: success


def test_a_right_password_signs_in_with_an_access_token_and_the_user(world):
    result = login(world)
    claims = world.signer.verify_access(result.tokens.access_token, now=world.clock.now())
    assert claims.user_id == result.me.user.id
    assert result.me.user.email == EMAIL and result.me.current.membership.role.name == "OWNER"


def test_keep_me_signed_in_gives_a_thirty_day_session_and_cookie(world):
    world.sessions.rows.clear()
    result = login(world, remember=True)
    assert result.tokens.cookie_max_age == Ttl.REFRESH_REMEMBER
    session = only_session(world)
    assert session.expires_at == world.clock.now() + timedelta(seconds=Ttl.REFRESH_REMEMBER)


def test_without_keep_me_signed_in_the_cookie_is_a_browser_session_cookie_and_lasts_a_day(world):
    world.sessions.rows.clear()
    result = login(world, remember=False)
    assert result.tokens.cookie_max_age is None
    assert only_session(world).expires_at == world.clock.now() + timedelta(
        seconds=Ttl.REFRESH_SESSION
    )


def test_remember_may_be_left_out_and_means_false(world):
    values = dict(email=EMAIL, password=PASSWORD, ip_address=IP, user_agent=AGENT, remember=None)
    assert world.sign_in.login(**values).tokens.cookie_max_age is None


def test_the_session_keeps_only_a_hash_of_the_refresh_value_plus_device_and_address(world):
    world.sessions.rows.clear()
    result = login(world)
    session = only_session(world)
    assert split_refresh_value(result.tokens.refresh_value) == session.id
    assert session.refresh_token_hash == sha256_hex(result.tokens.refresh_value)
    assert result.tokens.refresh_value not in str(session)
    assert (session.ip_address, session.device_name) == (IP, AGENT)


def test_the_device_name_is_cleaned_and_cut_to_the_column_size(world):
    world.sessions.rows.clear()
    login(world, user_agent="Agent\x00\n" + "x" * 500)
    name = only_session(world).device_name
    assert name is not None and len(name) <= 100 and "\x00" not in name and "\n" not in name


def test_a_missing_user_agent_is_fine(world):
    world.sessions.rows.clear()
    login(world, user_agent=None)
    assert only_session(world).device_name is None


def test_login_records_last_login_and_one_audit_row(world):
    result = login(world)
    assert world.users.rows[result.me.user.id].last_login == world.clock.now()
    event = world.audit.events[-1]
    assert (event.action, event.actor_type, event.actor_id) == (
        AuditAction.USER_LOGIN,
        ActorType.USER,
        result.me.user.id,
    )
    assert event.organization_id == result.me.current.organization.id


def test_the_session_and_the_audit_row_are_written_in_one_transaction(world):
    opened = world.uow.opened
    login(world)
    assert world.uow.opened == opened + 1


def test_a_password_that_needs_rehashing_is_stored_again(world, monkeypatch):
    monkeypatch.setattr(world.hasher, "needs_rehash", lambda encoded: True)
    monkeypatch.setattr(world.hasher, "verify", lambda raw, encoded: True)
    monkeypatch.setattr(world.hasher, "hash", lambda raw: "fake$upgraded")
    result = login(world)
    assert world.users.rows[result.me.user.id].password_hash == "fake$upgraded"


# ---- login: refused


def test_a_wrong_password_an_unknown_email_and_an_inactive_user_look_the_same(world):
    inactive_id = world.users.get_by_email(EMAIL).id
    world.users.rows[inactive_id] = replace(world.users.rows[inactive_id], is_active=False)
    world.register(email="other@example.com")
    world.clock.advance(31)
    other = world.verification.verify(
        email="other@example.com", code=world.last_code(), ip_address=IP
    )
    outcomes = []
    for email, password in (
        ("other@example.com", "Wrong-Password-1x"),
        ("nobody@example.com", PASSWORD),
        (EMAIL, PASSWORD),
    ):
        with pytest.raises(Unauthorized) as info:
            login(world, email=email, password=password)
        outcomes.append((info.value.code, info.value.detail, info.value.status))
    assert len(set(outcomes)) == 1 and outcomes[0][0] == "AUTH_BAD_CREDENTIALS"
    assert other.me.user.email == "other@example.com"


def test_an_unknown_email_costs_the_same_hashing_work_as_a_wrong_password(world):
    before = world.hasher.dummy_calls
    with pytest.raises(Unauthorized):
        login(world, email="nobody@example.com")
    assert world.hasher.dummy_calls == before + 1


def test_every_failed_attempt_is_audited_without_the_address_or_the_password(world):
    with pytest.raises(Unauthorized):
        login(world, password="Wrong-Password-1x")
    event = world.audit.events[-1]
    assert (event.action, event.actor_type) == (AuditAction.USER_LOGIN_FAILED, ActorType.SYSTEM)
    assert set(event.details) == {"email_hmac"}
    text = str(event)
    assert EMAIL not in text and "Wrong-Password" not in text


def test_a_failed_attempt_creates_no_session_and_writes_no_last_login(world):
    world.sessions.rows.clear()
    with pytest.raises(Unauthorized):
        login(world, password="Wrong-Password-1x")
    assert not world.sessions.rows
    assert world.users.get_by_email(EMAIL).last_login is None


def test_an_unverified_account_with_the_right_password_is_told_to_verify(world):
    world.register(email="new@example.com")
    world.clock.advance(31)
    with pytest.raises(Forbidden) as info:
        login(world, email="new@example.com")
    assert info.value.code == "AUTH_EMAIL_UNVERIFIED"
    assert all(
        s.user_id != world.users.get_by_email("new@example.com").id
        for s in world.sessions.rows.values()
    )


def test_an_unverified_account_with_a_wrong_password_learns_nothing(world):
    world.register(email="new@example.com")
    world.clock.advance(31)
    assert failing_code(
        lambda: login(world, email="new@example.com", password="Wrong-Pass-1x")
    ) == ("AUTH_BAD_CREDENTIALS")


# ---- login: limits and input


def login_from_other_address(world: AccountsWorld) -> SignInResult:
    return login(world, email="user100@example.com", ip_address="198.51.100.7")


def test_five_attempts_a_minute_per_email_then_even_the_right_password_is_refused(world):
    for _ in range(5):
        with pytest.raises(Unauthorized):
            login(world, password="Wrong-Password-1x")
    with pytest.raises(RateLimited) as info:
        login(world)
    assert info.value.retry_after >= 1
    world.clock.advance(61)
    assert login(world).me.user.email == EMAIL


def test_twenty_attempts_a_minute_per_address_across_different_emails(world):
    for index in range(20):
        with pytest.raises(Unauthorized):
            login(world, email=f"user{index}@example.com")
    with pytest.raises(RateLimited):
        login(world, email="user99@example.com")
    elsewhere = login_from_other_address  # another address has its own budget
    assert failing_code(lambda: elsewhere(world)) == "AUTH_BAD_CREDENTIALS"


def test_every_bad_field_is_reported_together(world):
    with pytest.raises(ValidationFailed) as info:
        login(world, email="not-an-email", password="", remember="yes")
    assert set(info.value.fields) == {"email", "password", "remember"}


def test_the_password_rules_for_new_passwords_do_not_apply_when_signing_in(world):
    # An old, weak password may still be the right one: only presence and length are checked.
    assert failing_code(lambda: login(world, password="short")) == "AUTH_BAD_CREDENTIALS"


# ---- refresh


def refresh(world: AccountsWorld, value: object, ip: str | None = IP) -> SignInResult:
    return world.sign_in.refresh(refresh_value=value, ip_address=ip)


def test_refresh_rotates_the_value_and_returns_a_new_access_token(world):
    first = login(world, remember=False)
    world.clock.advance(60)
    second = refresh(world, first.tokens.refresh_value)
    assert second.tokens.refresh_value != first.tokens.refresh_value
    assert second.tokens.access_token != first.tokens.access_token
    assert split_refresh_value(second.tokens.refresh_value) == split_refresh_value(
        first.tokens.refresh_value
    )
    session = world.sessions.rows[split_refresh_value(second.tokens.refresh_value)]
    assert session.refresh_token_hash == sha256_hex(second.tokens.refresh_value)
    assert session.last_used_at == world.clock.now()
    claims = world.signer.verify_access(second.tokens.access_token, now=world.clock.now())
    assert claims.session_id == session.id and second.me.user.email == EMAIL


def test_refresh_never_extends_the_session(world):
    first = login(world, remember=True)
    session_id = split_refresh_value(first.tokens.refresh_value)
    expires = world.sessions.rows[session_id].expires_at
    world.clock.advance(3600)
    refresh(world, first.tokens.refresh_value)
    assert world.sessions.rows[session_id].expires_at == expires


def test_a_remembered_session_cookie_lasts_for_the_time_the_session_has_left(world):
    first = login(world, remember=True)
    world.clock.advance(10 * 24 * 3600)
    second = refresh(world, first.tokens.refresh_value)
    assert second.tokens.cookie_max_age == Ttl.REFRESH_REMEMBER - 10 * 24 * 3600


def test_a_browser_session_stays_a_browser_session_after_refresh(world):
    first = login(world, remember=False)
    assert refresh(world, first.tokens.refresh_value).tokens.cookie_max_age is None


def test_the_old_value_is_dead_after_rotation_and_using_it_revokes_the_whole_session(world):
    first = login(world)
    second = refresh(world, first.tokens.refresh_value)
    with pytest.raises(Unauthorized) as info:
        refresh(world, first.tokens.refresh_value)  # a thief or a replay
    assert info.value.code == "AUTH_SESSION_INVALID"
    session = world.sessions.rows[split_refresh_value(first.tokens.refresh_value)]
    assert session.revoked_at == world.clock.now()
    # The legitimate holder of the newest value is cut off too: the family is burnt.
    assert failing_code(lambda: refresh(world, second.tokens.refresh_value)) == (
        "AUTH_SESSION_INVALID"
    )


def test_reuse_is_audited_with_the_user_and_the_session_but_no_secret(world):
    first = login(world)
    refresh(world, first.tokens.refresh_value)
    with pytest.raises(Unauthorized):
        refresh(world, first.tokens.refresh_value)
    event = world.audit.events[-1]
    session_id = split_refresh_value(first.tokens.refresh_value)
    assert event.action is AuditAction.SESSION_REUSE_DETECTED
    assert (event.actor_type, event.object_id) == (ActorType.USER, session_id)
    assert first.tokens.refresh_value not in str(event) and event.ip_address == IP
    assert world.uow.failed == 0  # revoking and auditing committed together, then we refused


def test_a_wrong_secret_for_a_live_session_revokes_it(world):
    first = login(world)
    session_id = split_refresh_value(first.tokens.refresh_value)
    forged = f"{session_id}.{'A' * 43}"
    with pytest.raises(Unauthorized):
        refresh(world, forged)
    assert world.sessions.rows[session_id].revoked_at is not None


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        123,
        ["a"],
        "garbage",
        "00000000-0000-0000-0000-000000000000.short",
        "00000000-0000-0000-0000-000000000001." + "A" * 43,
        "x" * 10_000,
    ],
)
def test_a_missing_or_malformed_or_unknown_value_is_the_same_401(world, value):
    before = dict(world.sessions.rows)
    with pytest.raises(Unauthorized) as info:
        refresh(world, value)
    assert (info.value.code, info.value.detail) == (
        "AUTH_SESSION_INVALID",
        Messages.AUTH_SESSION_INVALID.render(),
    )
    assert world.sessions.rows == before


def test_a_revoked_session_cannot_refresh_and_is_not_reported_as_reuse(world):
    first = login(world)
    world.sign_in.logout(refresh_value=first.tokens.refresh_value, ip_address=IP)
    audited = len(world.audit.events)
    assert failing_code(lambda: refresh(world, first.tokens.refresh_value)) == (
        "AUTH_SESSION_INVALID"
    )
    assert len(world.audit.events) == audited


def test_an_expired_session_cannot_refresh(world):
    first = login(world, remember=False)
    world.clock.advance(Ttl.REFRESH_SESSION + 1)
    assert failing_code(lambda: refresh(world, first.tokens.refresh_value)) == (
        "AUTH_SESSION_INVALID"
    )


def test_two_requests_with_the_same_value_at_once_end_the_session(world, monkeypatch):
    first = login(world)
    monkeypatch.setattr(world.sessions, "rotate", lambda **kwargs: False)  # lost the race
    with pytest.raises(Unauthorized):
        refresh(world, first.tokens.refresh_value)
    assert world.sessions.rows[split_refresh_value(first.tokens.refresh_value)].revoked_at


def test_a_deactivated_user_cannot_refresh_and_the_session_ends(world):
    first = login(world)
    user = world.users.get_by_email(EMAIL)
    world.users.rows[user.id] = replace(user, is_active=False)
    with pytest.raises(Unauthorized):
        refresh(world, first.tokens.refresh_value)
    assert world.sessions.rows[split_refresh_value(first.tokens.refresh_value)].revoked_at


# ---- logout


def test_logout_revokes_the_session_and_audits_it(world):
    first = login(world)
    assert world.sign_in.logout(refresh_value=first.tokens.refresh_value, ip_address=IP) is None
    assert world.sessions.rows[split_refresh_value(first.tokens.refresh_value)].revoked_at
    event = world.audit.events[-1]
    assert (event.action, event.actor_id) == (AuditAction.USER_LOGOUT, first.me.user.id)


def test_logout_kills_the_access_token_straight_away(world):
    first = login(world)
    header = f"Bearer {first.tokens.access_token}"
    assert world.authentication.authenticate(header).user_id == first.me.user.id
    world.sign_in.logout(refresh_value=first.tokens.refresh_value, ip_address=IP)
    assert failing_code(lambda: world.authentication.authenticate(header)) == (
        "AUTH_ACCESS_TOKEN_INVALID"
    )


@pytest.mark.parametrize(
    "value", [None, "", "garbage", 5, "00000000-0000-0000-0000-000000000001." + "A" * 43]
)
def test_logout_with_nothing_useful_still_succeeds_and_writes_nothing(world, value):
    audited = len(world.audit.events)
    assert world.sign_in.logout(refresh_value=value, ip_address=IP) is None
    assert len(world.audit.events) == audited


def test_logout_with_an_old_value_does_not_end_the_session(world):
    first = login(world)
    refresh(world, first.tokens.refresh_value)
    world.sign_in.logout(refresh_value=first.tokens.refresh_value, ip_address=IP)
    assert world.sessions.rows[split_refresh_value(first.tokens.refresh_value)].revoked_at is None


def test_logout_only_ends_that_device(world):
    one, two = login(world), login(world, user_agent="Other")
    world.sign_in.logout(refresh_value=one.tokens.refresh_value, ip_address=IP)
    assert world.sessions.rows[split_refresh_value(two.tokens.refresh_value)].revoked_at is None


# ---- AuthenticationService


def test_a_good_bearer_token_gives_the_user_and_session(world):
    result = login(world)
    principal = world.authentication.authenticate(f"Bearer {result.tokens.access_token}")
    assert principal.user_id == result.me.user.id
    assert principal.session_id == split_refresh_value(result.tokens.refresh_value)


@pytest.mark.parametrize(
    "header",
    [
        None,
        "",
        "Bearer",
        "Bearer ",
        "Basic abc",
        "bearer lower",
        "Bearer a.b.c",
        "Token x",
        "Bearer  x y",
    ],
)
def test_a_missing_or_malformed_authorization_header_is_refused(world, header):
    assert failing_code(lambda: world.authentication.authenticate(header)) == (
        "AUTH_ACCESS_TOKEN_INVALID"
    )


def test_an_expired_access_token_is_refused(world):
    result = login(world)
    world.clock.advance(Ttl.ACCESS_TOKEN + 1)
    assert (
        failing_code(
            lambda: world.authentication.authenticate(f"Bearer {result.tokens.access_token}")
        )
        == "AUTH_ACCESS_TOKEN_INVALID"
    )


def test_a_token_whose_session_expired_or_is_gone_is_refused(world):
    result = login(world, remember=False)
    world.sessions.rows.clear()
    assert (
        failing_code(
            lambda: world.authentication.authenticate(f"Bearer {result.tokens.access_token}")
        )
        == "AUTH_ACCESS_TOKEN_INVALID"
    )


def test_a_token_for_another_users_session_is_refused(world):
    world.register(email="other@example.com")
    world.clock.advance(31)
    other = world.verification.verify(
        email="other@example.com", code=world.last_code(), ip_address=IP
    )
    mine = login(world)
    forged = world.signer.issue_access(
        user_id=mine.me.user.id,
        session_id=split_refresh_value(other.tokens.refresh_value),
        now=world.clock.now(),
    )
    assert failing_code(lambda: world.authentication.authenticate(f"Bearer {forged.token}")) == (
        "AUTH_ACCESS_TOKEN_INVALID"
    )
