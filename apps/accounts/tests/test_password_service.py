"""PasswordService (change, forgot, reset) with fakes: no database, no HTTP."""

import re
from dataclasses import replace

import pytest

from apps.accounts.domain.entities import Principal, SignInResult
from apps.accounts.tests.fakes import FRONTEND_URL, VALID_REGISTRATION, AccountsWorld
from common.constants import ActorType, AuditAction, Ttl
from common.errors import RateLimited, Unauthorized, ValidationFailed
from common.security.refresh_tokens import split_refresh_value

EMAIL = VALID_REGISTRATION["email"]
OLD = VALID_REGISTRATION["password"]
NEW = "Copper-Meadow-Gate-55"
IP = "203.0.113.9"


@pytest.fixture
def world() -> AccountsWorld:
    w = AccountsWorld()
    w.verified_user()
    return w


def principal_of(result: SignInResult) -> Principal:
    return Principal(result.me.user.id, split_refresh_value(result.tokens.refresh_value))


def sign_in(world: AccountsWorld, agent: str = "A") -> SignInResult:
    return world.sign_in.login(
        email=EMAIL,
        password=NEW if world.password_is_new else OLD,
        remember=False,
        ip_address=IP,
        user_agent=agent,
    )


def change(world: AccountsWorld, who: Principal, **overrides: object) -> None:
    values = dict(current=OLD, password=NEW, ip_address=IP)
    world.passwords.change(principal=who, **{**values, **overrides})


def field_codes(call) -> dict[str, list[str]]:
    with pytest.raises(ValidationFailed) as info:
        call()
    return {k: [i.message.name for i in v] for k, v in info.value.fields.items()}


def stored_hash(world: AccountsWorld) -> str:
    return world.users.get_by_email(EMAIL).password_hash


def link_token(world: AccountsWorld) -> str:
    match = re.search(r"new-password\?token=([\w-]+)", world.email.outbox[-1].text_body)
    assert match, "the last email carries no reset link"
    return match.group(1)


@pytest.fixture(autouse=True)
def _flag(world):
    world.password_is_new = False


# ---- change


def test_change_stores_the_new_hash_and_keeps_only_the_current_session(world):
    current, other = sign_in(world, "A"), sign_in(world, "B")
    change(world, principal_of(current))
    assert stored_hash(world) == world.hasher.hash(NEW)
    rows = world.sessions.rows
    assert rows[split_refresh_value(current.tokens.refresh_value)].revoked_at is None
    assert rows[split_refresh_value(other.tokens.refresh_value)].revoked_at is not None


def test_the_other_devices_lose_access_and_refresh(world):
    current, other = sign_in(world, "A"), sign_in(world, "B")
    change(world, principal_of(current))
    header = f"Bearer {other.tokens.access_token}"
    with pytest.raises(Unauthorized):
        world.authentication.authenticate(header)
    with pytest.raises(Unauthorized):
        world.sign_in.refresh(refresh_value=other.tokens.refresh_value, ip_address=IP)
    world.authentication.authenticate(f"Bearer {current.tokens.access_token}")


def test_the_old_password_stops_working_and_the_new_one_works(world):
    current = sign_in(world)
    change(world, principal_of(current))
    world.password_is_new = True
    world.clock.advance(61)
    with pytest.raises(Unauthorized):
        world.sign_in.login(
            email=EMAIL, password=OLD, remember=False, ip_address=IP, user_agent=None
        )
    assert sign_in(world).me.user.email == EMAIL


def test_change_is_audited_without_any_password_and_the_user_is_told(world):
    current = sign_in(world)
    change(world, principal_of(current))
    event = world.audit.events[-1]
    assert (event.action, event.actor_type, event.actor_id) == (
        AuditAction.USER_PASSWORD_CHANGE,
        ActorType.USER,
        current.me.user.id,
    )
    assert OLD not in str(event) and NEW not in str(event)
    notice = world.email.outbox[-1]
    assert notice.to == EMAIL and "password was changed" in notice.text_body
    assert OLD not in notice.text_body and NEW not in notice.text_body


def test_the_change_and_the_revocations_are_one_transaction(world):
    current = sign_in(world)
    opened = world.uow.opened
    change(world, principal_of(current))
    assert world.uow.opened == opened + 1


def test_a_wrong_current_password_changes_nothing(world):
    current = sign_in(world)
    before = stored_hash(world)
    emails = len(world.email.outbox)
    codes = field_codes(lambda: change(world, principal_of(current), current="Wrong-Pass-77x"))
    assert codes == {"current": ["AUTH_WRONG_CURRENT_PASSWORD"]}
    assert stored_hash(world) == before and len(world.email.outbox) == emails
    assert world.sessions.rows[split_refresh_value(current.tokens.refresh_value)].revoked_at is None


def test_the_new_password_follows_the_same_rules_as_sign_up(world):
    who = principal_of(sign_in(world))
    assert field_codes(lambda: change(world, who, password="short")) == {
        "password": ["VALIDATION_PASSWORD_TOO_SHORT"]
    }
    assert (
        "VALIDATION_PASSWORD_NEEDS_DIGIT"
        in field_codes(lambda: change(world, who, password="NoDigitsHereAtAll"))["password"]
    )
    assert field_codes(lambda: change(world, who, password="Ali-Raza-Strong-77"))["password"] == [
        "VALIDATION_PASSWORD_CONTAINS_NAME"
    ]


def test_the_new_password_may_not_equal_the_current_one(world):
    who = principal_of(sign_in(world))
    assert field_codes(lambda: change(world, who, password=OLD)) == {
        "password": ["VALIDATION_PASSWORD_SAME_AS_CURRENT"]
    }


def test_missing_fields_are_reported_together(world):
    who = principal_of(sign_in(world))
    assert set(field_codes(lambda: change(world, who, current=None, password=None))) == {
        "current",
        "password",
    }


def test_five_attempts_per_quarter_hour_then_even_the_right_one_is_refused(world):
    who = principal_of(sign_in(world))
    for _ in range(5):
        field_codes(lambda: change(world, who, current="Wrong-Pass-77x"))
    with pytest.raises(RateLimited):
        change(world, who)
    world.clock.advance(901)
    change(world, who)


def test_the_limit_is_per_user_not_shared(world):
    mine = principal_of(sign_in(world))
    other = world.verified_user(email="other@example.com", name="Sana Malik")
    for _ in range(5):
        field_codes(lambda: change(world, mine, current="Wrong-Pass-77x"))
    with pytest.raises(RateLimited):
        change(world, mine)
    change(world, principal_of(other))


def test_a_user_who_no_longer_exists_or_is_inactive_is_refused(world):
    who = principal_of(sign_in(world))
    world.users.rows[who.user_id] = replace(world.users.rows[who.user_id], is_active=False)
    with pytest.raises(Unauthorized):
        change(world, who)


def test_if_the_password_changed_under_us_the_attempt_fails_cleanly(world, monkeypatch):
    who = principal_of(sign_in(world))
    monkeypatch.setattr(world.users, "change_password", lambda **kwargs: False)
    assert field_codes(lambda: change(world, who)) == {"current": ["AUTH_WRONG_CURRENT_PASSWORD"]}


# ---- forgot password


def test_a_known_address_gets_a_link_that_points_at_the_new_password_page(world):
    world.passwords.request_reset(email=EMAIL, ip_address=IP)
    mail = world.email.outbox[-1]
    assert mail.to == EMAIL and mail.subject == "Reset your Nudge password"
    assert f"{FRONTEND_URL}/new-password?token=" in mail.text_body
    assert (
        OLD not in mail.text_body
        and world.users.get_by_email(EMAIL).password_hash not in mail.text_body
    )


def test_a_known_address_is_audited_without_the_address(world):
    world.passwords.request_reset(email=EMAIL, ip_address=IP)
    event = world.audit.events[-1]
    assert event.action is AuditAction.USER_PASSWORD_RESET_REQUEST
    assert EMAIL not in str(event) and event.object_id == world.users.get_by_email(EMAIL).id


def test_an_unknown_address_gets_nothing_and_leaves_no_audit_row(world):
    emails, audited = len(world.email.outbox), len(world.audit.events)
    assert world.passwords.request_reset(email="nobody@example.com", ip_address=IP) is None
    assert (len(world.email.outbox), len(world.audit.events)) == (emails, audited)


def test_an_inactive_account_gets_no_link(world):
    user = world.users.get_by_email(EMAIL)
    world.users.rows[user.id] = replace(user, is_active=False)
    emails = len(world.email.outbox)
    world.passwords.request_reset(email=EMAIL, ip_address=IP)
    assert len(world.email.outbox) == emails


def test_the_address_is_cleaned_before_it_is_used(world):
    world.passwords.request_reset(email="  ALI@Example.com ", ip_address=IP)
    assert world.email.outbox[-1].subject == "Reset your Nudge password"


def test_three_requests_an_hour_per_address_known_or_not(world):
    for email in (EMAIL, "nobody@example.com"):
        for _ in range(3):
            world.passwords.request_reset(email=email, ip_address=IP)
        with pytest.raises(RateLimited):
            world.passwords.request_reset(email=email, ip_address=IP)
    world.clock.advance(3601)
    world.passwords.request_reset(email=EMAIL, ip_address=IP)


def test_ten_requests_an_hour_per_address_of_the_caller(world):
    for index in range(10):
        world.passwords.request_reset(email=f"user{index}@example.com", ip_address=IP)
    with pytest.raises(RateLimited):
        world.passwords.request_reset(email="user11@example.com", ip_address=IP)
    world.passwords.request_reset(email="user11@example.com", ip_address="198.51.100.4")


def test_a_malformed_address_is_a_field_error(world):
    assert field_codes(lambda: world.passwords.request_reset(email="nope", ip_address=IP)) == {
        "email": ["VALIDATION_EMAIL_INVALID"]
    }


# ---- reset with the link


def reset(world: AccountsWorld, token: object, password: object = NEW) -> None:
    world.passwords.confirm_reset(token=token, password=password, ip_address=IP)


def invalid_token(call) -> None:
    with pytest.raises(ValidationFailed) as info:
        call()
    assert info.value.code == "AUTH_INVALID_TOKEN" and not info.value.fields


def test_the_link_sets_the_new_password_and_signs_everyone_out(world):
    one, two = sign_in(world, "A"), sign_in(world, "B")
    world.passwords.request_reset(email=EMAIL, ip_address=IP)
    reset(world, link_token(world))
    assert stored_hash(world) == world.hasher.hash(NEW)
    assert all(s.revoked_at is not None for s in world.sessions.rows.values())
    with pytest.raises(Unauthorized):
        world.authentication.authenticate(f"Bearer {one.tokens.access_token}")
    with pytest.raises(Unauthorized):
        world.authentication.authenticate(f"Bearer {two.tokens.access_token}")


def test_the_new_password_signs_in_and_the_old_one_does_not(world):
    world.passwords.request_reset(email=EMAIL, ip_address=IP)
    reset(world, link_token(world))
    world.password_is_new = True
    assert sign_in(world).me.user.email == EMAIL
    world.clock.advance(61)
    with pytest.raises(Unauthorized):
        world.sign_in.login(
            email=EMAIL, password=OLD, remember=False, ip_address=IP, user_agent=None
        )


def test_a_link_works_once(world):
    world.passwords.request_reset(email=EMAIL, ip_address=IP)
    token = link_token(world)
    reset(world, token)
    invalid_token(lambda: reset(world, token, "Another-Strong-Pass-88"))
    assert stored_hash(world) == world.hasher.hash(NEW)


def test_using_one_link_kills_the_other_links(world):
    world.passwords.request_reset(email=EMAIL, ip_address=IP)
    first = link_token(world)
    world.clock.advance(1)
    world.passwords.request_reset(email=EMAIL, ip_address=IP)
    second = link_token(world)
    assert first != second
    reset(world, second)
    invalid_token(lambda: reset(world, first, "Another-Strong-Pass-88"))


def test_a_link_expires_after_an_hour(world):
    world.passwords.request_reset(email=EMAIL, ip_address=IP)
    token = link_token(world)
    world.clock.advance(Ttl.RESET_LINK)
    invalid_token(lambda: reset(world, token))
    assert stored_hash(world) == world.hasher.hash(OLD)


def test_signing_in_cancels_an_open_link(world):
    world.passwords.request_reset(email=EMAIL, ip_address=IP)
    token = link_token(world)
    sign_in(world)
    invalid_token(lambda: reset(world, token))


@pytest.mark.parametrize("token", [None, "", "x", 5, ["a"], "a-b-c", "é" * 30, "z" * 500])
def test_anything_that_is_not_a_good_token_is_the_same_400(world, token):
    invalid_token(lambda: reset(world, token))


def test_a_weak_password_is_a_field_error_and_the_link_stays_usable(world):
    world.passwords.request_reset(email=EMAIL, ip_address=IP)
    token = link_token(world)
    assert field_codes(lambda: reset(world, token, "short")) == {
        "password": ["VALIDATION_PASSWORD_TOO_SHORT"]
    }
    assert (
        "VALIDATION_PASSWORD_CONTAINS_NAME"
        in field_codes(lambda: reset(world, token, "Raza-Strong-Gate-77"))["password"]
    )
    reset(world, token)


def test_if_the_password_changed_under_us_the_link_counts_as_used(world, monkeypatch):
    world.passwords.request_reset(email=EMAIL, ip_address=IP)
    token = link_token(world)
    monkeypatch.setattr(world.users, "change_password", lambda **kwargs: False)
    invalid_token(lambda: reset(world, token))


def test_reset_is_audited_and_the_owner_is_told_without_any_secret(world):
    world.passwords.request_reset(email=EMAIL, ip_address=IP)
    token = link_token(world)
    reset(world, token)
    event = world.audit.events[-1]
    assert event.action is AuditAction.USER_PASSWORD_RESET
    assert token not in str(event) and NEW not in str(event)
    notice = world.email.outbox[-1]
    assert notice.to == EMAIL and "password was changed" in notice.text_body
    assert token not in notice.text_body and NEW not in notice.text_body


def test_reset_is_one_transaction(world):
    world.passwords.request_reset(email=EMAIL, ip_address=IP)
    opened = world.uow.opened
    reset(world, link_token(world))
    assert world.uow.opened == opened + 1


def test_ten_tries_an_hour_per_address_then_even_a_good_link_is_refused(world):
    world.passwords.request_reset(email=EMAIL, ip_address=IP)
    token = link_token(world)
    for _ in range(10):
        invalid_token(lambda: reset(world, "0" * 32 + "-1-" + "0" * 64))
    with pytest.raises(RateLimited):
        reset(world, token)


def test_resetting_does_not_make_an_unverified_email_verified(world):
    world.register(email="new@example.com", name="Sana Malik")
    world.passwords.request_reset(email="new@example.com", ip_address=IP)
    reset(world, link_token(world))
    assert world.users.get_by_email("new@example.com").email_verified_at is None
