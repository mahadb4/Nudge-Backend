"""RegistrationService with fake repositories: no database, no HTTP."""

import re

import pytest

from apps.accounts.domain.entities import User
from apps.accounts.domain.enums import CodeCheck
from apps.accounts.tests.fakes import FRONTEND_URL, VALID_REGISTRATION, AccountsWorld
from common.constants import AccountType, ActorType, AuditAction, HmacNamespace, Role
from common.errors import RateLimited, ServiceUnavailable, ValidationFailed


@pytest.fixture
def world() -> AccountsWorld:
    return AccountsWorld()


def failing_fields(world: AccountsWorld, **overrides: object) -> dict[str, list[str]]:
    with pytest.raises(ValidationFailed) as info:
        world.register(**overrides)
    return {name: [i.message.name for i in issues] for name, issues in info.value.fields.items()}


# ---- a new address


def test_a_new_business_gets_a_user_an_organization_an_owner_membership_and_default_stages(world):
    world.register()
    (user,) = world.users.rows.values()
    (organization,) = world.organizations.rows.values()
    (membership,) = world.memberships.rows
    assert (user.email, user.full_name, user.timezone) == (
        "ali@example.com",
        "Ali Raza",
        "Asia/Karachi",
    )
    assert (organization.name, organization.account_type) == ("Acme Sales", AccountType.BUSINESS)
    assert (membership.user_id, membership.organization_id, membership.role) == (
        user.id,
        organization.id,
        Role.OWNER,
    )
    assert world.seeder.seeded == [organization.id]


def test_an_individual_organization_is_named_after_the_person(world):
    world.register(account_type="individual", company=None)
    (organization,) = world.organizations.rows.values()
    assert (organization.name, organization.account_type) == ("Ali Raza", AccountType.INDIVIDUAL)


def test_the_password_is_stored_hashed_and_never_in_the_clear(world):
    world.register()
    (user,) = world.users.rows.values()
    assert user.password_hash == world.hasher.hash("Harbor-Lantern-42") != "Harbor-Lantern-42"


def test_everything_is_written_inside_one_transaction(world):
    world.register()
    assert world.uow.opened == 1 and world.uow.failed == 0


def test_a_code_is_emailed_to_the_address(world):
    world.register()
    (message,) = world.email.outbox
    assert message.to == "ali@example.com" and message.subject == "Your Nudge verification code"
    assert re.fullmatch(r"\d{6}", world.last_code())


def test_the_email_is_cleaned_before_it_is_used(world):
    world.register(email="  ALI@Example.COM ")
    assert [u.email for u in world.users.rows.values()] == ["ali@example.com"]
    assert world.email.outbox[0].to == "ali@example.com"


def test_one_audit_row_is_written_with_no_secrets(world):
    world.register()
    (event,) = world.audit.events
    (user,) = world.users.rows.values()
    (organization,) = world.organizations.rows.values()
    assert (event.action, event.actor_type, event.actor_id, event.organization_id) == (
        AuditAction.USER_REGISTER,
        ActorType.USER,
        user.id,
        organization.id,
    )
    assert event.details == {"account_type": "business"} and event.ip_address == "203.0.113.9"
    assert "ali@example.com" not in str(event) and "Harbor" not in str(event)


def test_the_slow_password_hash_runs_before_the_transaction_opens(world):
    order: list[str] = []
    world.hasher.hash = lambda raw: order.append("hash") or "h"  # type: ignore[method-assign]
    original = world.uow.atomic

    def spy():
        order.append("transaction")
        return original()

    world.uow.atomic = spy  # type: ignore[method-assign]
    world.register()
    assert order == ["hash", "transaction"]


# ---- validation


def test_every_bad_field_is_reported_at_once_and_nothing_is_created(world):
    fields = failing_fields(
        world, name="A", email="nope", password="short", account_type="team", timezone="Mars/Base"
    )
    assert fields == {
        "name": ["VALIDATION_TOO_SHORT"],
        "email": ["VALIDATION_EMAIL_INVALID"],
        "password": ["VALIDATION_PASSWORD_TOO_SHORT"],
        "type": ["VALIDATION_CHOICE_INVALID"],
        "timezone": ["VALIDATION_TIMEZONE_INVALID"],
    }
    assert not world.users.rows and not world.email.outbox and not world.audit.events


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"company": None}, {"company": ["VALIDATION_REQUIRED"]}),
        ({"company": "A"}, {"company": ["VALIDATION_TOO_SHORT"]}),
        ({"company": "<b>Acme</b>"}, {"company": ["VALIDATION_MARKUP_NOT_ALLOWED"]}),
        (
            {"account_type": "individual", "company": "Acme"},
            {"company": ["VALIDATION_COMPANY_NOT_ALLOWED"]},
        ),
        ({"account_type": "Business"}, {"type": ["VALIDATION_CHOICE_INVALID"]}),
        (
            {"password": "Mahad-Secure-9", "email": "mahad@example.com"},
            {"password": ["VALIDATION_PASSWORD_CONTAINS_EMAIL"]},
        ),
        (
            {"password": "Baloch-Secure-9", "name": "Mahad Baloch"},
            {"password": ["VALIDATION_PASSWORD_CONTAINS_NAME"]},
        ),
        ({"password": "Password123!"}, {"password": ["VALIDATION_PASSWORD_TOO_COMMON"]}),
        ({"name": 5}, {"name": ["VALIDATION_INVALID_TYPE"]}),
        ({"email": None}, {"email": ["VALIDATION_REQUIRED"]}),
    ],
)
def test_field_rules(world, overrides, expected):
    assert failing_fields(world, **overrides) == expected


def test_a_missing_company_is_fine_for_an_individual(world):
    world.register(account_type="individual", company=None)


# ---- a known address: same answer, no new rows


def test_a_verified_address_gets_a_notice_email_and_no_new_rows(world):
    world.register()
    (user,) = world.users.rows.values()
    world.users.mark_email_verified(user.id, world.clock.now())
    world.clock.advance(31)
    world.register(name="Someone Else", password="Another-Password-77")
    assert (
        len(world.users.rows) == 1
        and len(world.organizations.rows) == 1
        and len(world.memberships.rows) == 1
    )
    notice = world.email.outbox[-1]
    assert (
        notice.subject == "Someone tried to sign up"
        and f"{FRONTEND_URL}/sign-in" in notice.text_body
    )
    assert not re.search(r"\d{6}", notice.text_body)


def test_an_unverified_address_gets_a_fresh_code_instead(world):
    world.register()
    world.clock.advance(31)
    world.register()
    assert len(world.users.rows) == 1
    assert [m.subject for m in world.email.outbox] == ["Your Nudge verification code"] * 2
    assert {m.to for m in world.email.outbox} == {"ali@example.com"}


def test_a_verified_address_costs_the_same_hashing_work_as_a_new_one(world):
    world.register()
    (user,) = world.users.rows.values()
    world.users.mark_email_verified(user.id, world.clock.now())
    assert world.hasher.dummy_calls == 0
    world.clock.advance(31)
    world.register()
    assert world.hasher.dummy_calls == 1


def test_a_verified_address_is_audited_without_the_address_itself(world):
    world.register()
    (user,) = world.users.rows.values()
    world.users.mark_email_verified(user.id, world.clock.now())
    world.clock.advance(31)
    world.register()
    event = world.audit.events[-1]
    assert (event.action, event.actor_type, event.organization_id) == (
        AuditAction.USER_REGISTER_EXISTING,
        ActorType.SYSTEM,
        None,
    )
    assert set(event.details) == {"email_hmac"} and "ali@example.com" not in str(event.details)


# ---- an unverified address: the latest registration wins

ATTACKER = dict(
    name="Mallory Evil",
    company=None,
    password="Silver-Orchard-Bell-99",
    account_type="individual",
    timezone="UTC",
)


def only_user(world: AccountsWorld) -> User:
    (user,) = world.users.rows.values()
    return user


def email_hash(world: AccountsWorld) -> str:
    return world.digests.digest(HmacNamespace.EMAIL, "ali@example.com")


def test_the_latest_registration_replaces_password_name_and_organization(world):
    world.register()
    world.clock.advance(31)
    world.register(
        name="Sana Malik",
        company="Second Co",
        password="Copper-Meadow-Gate-55",
        account_type="business",
        timezone="Europe/London",
    )
    user = only_user(world)
    (organization,) = world.organizations.rows.values()
    assert user.password_hash == world.hasher.hash("Copper-Meadow-Gate-55")
    assert (user.full_name, user.timezone) == ("Sana Malik", "Europe/London")
    assert (organization.name, organization.account_type, organization.timezone) == (
        "Second Co",
        AccountType.BUSINESS,
        "Europe/London",
    )
    assert len(world.organizations.rows) == len(world.memberships.rows) == 1


def test_the_replacement_can_change_the_organization_type(world):
    world.register()
    world.clock.advance(31)
    world.register(account_type="individual", company=None)
    (organization,) = world.organizations.rows.values()
    assert (organization.name, organization.account_type) == ("Ali Raza", AccountType.INDIVIDUAL)


def test_the_replacement_is_one_transaction_with_an_audit_row_and_no_secrets(world):
    world.register()
    world.clock.advance(31)
    opened = world.uow.opened
    world.register(password="Copper-Meadow-Gate-55")
    assert world.uow.opened == opened + 1
    event = world.audit.events[-1]
    (organization,) = world.organizations.rows.values()
    assert (event.action, event.actor_type, event.organization_id) == (
        AuditAction.USER_REGISTER_REPLACE,
        ActorType.SYSTEM,
        organization.id,
    )
    assert set(event.details) == {"email_hmac"}
    assert "ali@example.com" not in str(event.details)
    assert "Second-Password" not in str(event.details)


def test_the_replacement_hashes_the_new_password_for_real_not_a_dummy(world):
    world.register()
    world.clock.advance(31)
    world.register()
    assert world.hasher.dummy_calls == 0


def test_the_previous_code_stops_working_and_a_new_one_is_issued(world):
    world.register()
    first_code = world.last_code()
    world.clock.advance(31)
    world.register(password="Copper-Meadow-Gate-55")
    second_code = world.last_code()
    assert first_code != second_code
    assert world.code_repository.check(email_hash(world), first_code) is CodeCheck.WRONG
    assert len(world.email.outbox) == 2


def test_the_wrong_try_counter_starts_again_with_the_new_code(world):
    world.register()
    bad = "000000" if world.last_code() != "000000" else "111111"
    for _ in range(4):
        world.code_repository.check(email_hash(world), bad)
    world.clock.advance(31)
    world.register()
    assert world.code_repository.check(email_hash(world), bad) is CodeCheck.WRONG
    assert world.code_repository.check(email_hash(world), world.last_code()) is CodeCheck.OK


def verify_with_latest_code(world: AccountsWorld):
    return world.verification.verify(
        email="ali@example.com", code=world.last_code(), ip_address="203.0.113.9"
    )


def test_attacker_first_then_the_victim_who_verifies_has_the_victims_password(world):
    world.register(**ATTACKER)
    world.clock.advance(31)
    world.register(name="Vera Khan", password="Quiet-Harbor-Lamp-11")
    verify_with_latest_code(world)
    user = only_user(world)
    assert user.password_hash == world.hasher.hash("Quiet-Harbor-Lamp-11")
    assert user.password_hash != world.hasher.hash(ATTACKER["password"])
    assert user.full_name == "Vera Khan" and user.email_verified_at is not None


def test_victim_first_then_the_attacker_the_old_code_no_longer_works(world):
    world.register(name="Vera Khan", password="Quiet-Harbor-Lamp-11")
    victims_code = world.last_code()
    world.clock.advance(31)
    world.register(**ATTACKER)
    with pytest.raises(ValidationFailed):
        world.verification.verify(
            email="ali@example.com", code=victims_code, ip_address="203.0.113.9"
        )
    assert only_user(world).email_verified_at is None
    assert only_user(world).password_hash == world.hasher.hash(ATTACKER["password"])
    verify_with_latest_code(world)  # only the code from the newest sign-up verifies
    assert only_user(world).email_verified_at is not None


def test_a_verified_address_changes_nothing_but_gets_the_notice(world):
    world.register()
    world.users.mark_email_verified(only_user(world).id, world.clock.now())
    before_user = only_user(world)
    (before_org,) = world.organizations.rows.values()
    world.clock.advance(31)
    world.register(**ATTACKER)
    assert only_user(world) == before_user
    assert tuple(world.organizations.rows.values()) == (before_org,)
    assert world.email.outbox[-1].subject == "Someone tried to sign up"
    assert world.audit.events[-1].action is AuditAction.USER_REGISTER_EXISTING


def test_if_the_owner_verifies_just_before_our_update_the_notice_is_sent_instead(world):
    world.register()
    before_hash = only_user(world).password_hash
    world.users.verify_before_next_update = world.clock.now()
    world.clock.advance(31)
    world.register(**ATTACKER)
    assert only_user(world).password_hash == before_hash
    assert world.email.outbox[-1].subject == "Someone tried to sign up"
    assert AuditAction.USER_REGISTER_REPLACE not in [e.action for e in world.audit.events]


def test_two_sign_ups_racing_for_one_address_end_like_a_known_address(world):
    world.users.race_on_next_create = True
    world.register()
    assert len(world.users.rows) == 1  # only the winner's row
    assert not world.organizations.rows and not world.memberships.rows
    assert world.email.outbox[-1].subject == "Your Nudge verification code"
    assert world.uow.failed == 1  # our transaction was rolled back


def test_the_caller_sees_no_difference_between_new_and_known(world):
    assert world.registration.register(**VALID_REGISTRATION, ip_address="203.0.113.9") is None
    world.clock.advance(31)
    assert world.registration.register(**VALID_REGISTRATION, ip_address="203.0.113.9") is None


# ---- limits and failures


def test_a_second_sign_up_for_the_same_address_within_30_seconds_is_refused(world):
    world.register()
    with pytest.raises(RateLimited):
        world.register()
    world.clock.advance(30)
    world.register()


def test_the_30_second_rule_applies_to_unknown_and_known_addresses_alike(world):
    for email in ("new@example.com", "ali@example.com"):
        world.register(email=email)
        with pytest.raises(RateLimited):
            world.register(email=email)


def test_an_ip_address_can_sign_up_ten_times_an_hour(world):
    for index in range(10):
        world.register(email=f"user{index}@example.com")
    with pytest.raises(RateLimited):
        world.register(email="user10@example.com")
    assert len(world.users.rows) == 10


def test_another_ip_address_is_not_affected(world):
    for index in range(10):
        world.register(email=f"user{index}@example.com")
    world.register(email="other@example.com", ip_address="198.51.100.4")


def test_a_failure_inside_the_transaction_sends_no_email_and_writes_no_audit_row(world):
    world.seeder.error = ServiceUnavailable()
    with pytest.raises(ServiceUnavailable):
        world.register()
    assert world.uow.failed == 1 and not world.email.outbox and not world.audit.events


def test_an_unknown_client_address_is_still_limited(world):
    for index in range(10):
        world.register(email=f"user{index}@example.com", ip_address=None)
    with pytest.raises(RateLimited):
        world.register(email="x@example.com", ip_address=None)


def test_returns_nothing_the_client_could_use(world):
    assert world.registration.register(**VALID_REGISTRATION, ip_address=None) is None
    assert isinstance(next(iter(world.users.rows.values())), User)
