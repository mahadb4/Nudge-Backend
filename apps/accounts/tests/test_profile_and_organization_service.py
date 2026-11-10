"""ProfileService and OrganizationService with fakes."""

from datetime import time

import pytest

from apps.accounts.services.organization_service import OrganizationService
from apps.accounts.services.profile_service import ProfileService
from apps.accounts.services.user_validator import UserValidator
from apps.accounts.tests.fakes import AccountsWorld
from common.constants import ActorType, AuditAction, Role
from common.errors import Forbidden, ValidationFailed
from common.tenancy import TenantContext

IP = "203.0.113.9"


@pytest.fixture
def world() -> AccountsWorld:
    w = AccountsWorld()
    w.verified_user()
    w.profile = ProfileService(
        validator=UserValidator(), users=w.users, me=w.me_service, audit=w.audit, uow=w.uow
    )
    w.org_service = OrganizationService(
        validator=UserValidator(), organizations=w.organizations, audit=w.audit, uow=w.uow
    )
    return w


def me_id(world):
    return world.users.get_by_email("ali@example.com").id


def patch(world, **sent):
    return world.profile.update(
        user_id=me_id(world), organization_header=None, sent=sent, ip_address=IP
    )


def codes(call) -> dict[str, list[str]]:
    with pytest.raises(ValidationFailed) as info:
        call()
    return {k: [i.message.name for i in v] for k, v in info.value.fields.items()}


def context(world, role=Role.OWNER) -> TenantContext:
    return TenantContext(me_id(world), next(iter(world.organizations.rows)), role)


# ---- profile


def test_only_the_sent_fields_change_and_they_are_cleaned(world):
    me = patch(world, name="  Ali   Second ", phone="+92 300 1234567", timezone="Europe/London")
    assert (me.user.full_name, me.user.phone, me.user.timezone) == (
        "Ali Second",
        "+923001234567",
        "Europe/London",
    )
    assert me.user.email == "ali@example.com"


def test_quiet_hours_are_stored_as_times_and_can_be_cleared(world):
    me = patch(world, quiet_hours_start="22:00", quiet_hours_end="07:30")
    assert (me.user.quiet_hours_start, me.user.quiet_hours_end) == (time(22), time(7, 30))
    cleared = patch(world, quiet_hours_start=None, quiet_hours_end=None)
    assert cleared.user.quiet_hours_start is None and cleared.user.quiet_hours_end is None


def test_null_phone_clears_it(world):
    patch(world, phone="+923001234567")
    assert patch(world, phone=None).user.phone is None


def test_quiet_hours_must_be_set_or_cleared_together(world):
    assert codes(lambda: patch(world, quiet_hours_start="22:00")) == {
        "quiet_hours_end": ["VALIDATION_QUIET_HOURS_PAIR"]
    }
    patch(world, quiet_hours_start="22:00", quiet_hours_end="07:00")
    assert codes(lambda: patch(world, quiet_hours_end=None)) == {
        "quiet_hours_end": ["VALIDATION_QUIET_HOURS_PAIR"]
    }
    assert patch(world, quiet_hours_start="21:00").user.quiet_hours_start == time(21)


@pytest.mark.parametrize(
    "sent, expected",
    [
        ({"name": None}, {"name": ["VALIDATION_REQUIRED"]}),
        ({"name": "A"}, {"name": ["VALIDATION_TOO_SHORT"]}),
        ({"name": "<b>Ali</b>"}, {"name": ["VALIDATION_MARKUP_NOT_ALLOWED"]}),
        ({"phone": "03001234567"}, {"phone": ["VALIDATION_PHONE_NEEDS_PLUS"]}),
        ({"phone": "+1"}, {"phone": ["VALIDATION_PHONE_INVALID"]}),
        ({"phone": "+99999999999999999"}, {"phone": ["VALIDATION_PHONE_INVALID"]}),
        ({"phone": 5}, {"phone": ["VALIDATION_INVALID_TYPE"]}),
        ({"timezone": "Mars/Base"}, {"timezone": ["VALIDATION_TIMEZONE_INVALID"]}),
        ({"timezone": None}, {"timezone": ["VALIDATION_REQUIRED"]}),
        (
            {"quiet_hours_start": "25:00", "quiet_hours_end": "7:00"},
            {
                "quiet_hours_start": ["VALIDATION_TIME_INVALID"],
                "quiet_hours_end": ["VALIDATION_TIME_INVALID"],
            },
        ),
    ],
)
def test_field_rules(world, sent, expected):
    assert codes(lambda: patch(world, **sent)) == expected


def test_a_bad_field_stops_every_change(world):
    before = world.users.get_by_email("ali@example.com")
    codes(lambda: patch(world, name="Fine Name", phone="nope"))
    assert world.users.get_by_email("ali@example.com") == before


def test_an_update_is_audited_with_field_names_only(world):
    patch(world, name="Ali Second", phone="+923001234567")
    event = world.audit.events[-1]
    assert (event.action, event.actor_type) == (AuditAction.USER_PROFILE_UPDATE, ActorType.USER)
    assert event.details == {"fields": ["full_name", "phone"]}
    assert "+92" not in str(event) and "Second" not in str(event)


def test_sending_nothing_writes_nothing(world):
    audited, opened = len(world.audit.events), world.uow.opened
    patch(world)
    assert (len(world.audit.events), world.uow.opened) == (audited, opened)


# ---- organization


def test_any_member_reads_the_current_organization(world):
    organization = world.org_service.get_current(context(world, Role.MEMBER))
    assert organization.name == "Acme Sales" and organization.automation_paused is False


def update(world, role=Role.OWNER, **sent):
    return world.org_service.update_current(context(world, role), sent, IP)


@pytest.mark.parametrize("role", [Role.OWNER, Role.ADMIN])
def test_owner_and_admin_can_rename_and_change_the_time_zone(world, role):
    organization = update(world, role, name="  New   Name ", timezone="UTC")
    assert (organization.name, organization.timezone) == ("New Name", "UTC")
    event = world.audit.events[-1]
    assert event.action is AuditAction.ORGANIZATION_UPDATE
    assert event.details == {"fields": ["name", "timezone"]}
    assert event.organization_id == context(world).organization_id


@pytest.mark.parametrize("role", [Role.MANAGER, Role.MEMBER])
def test_other_roles_are_refused_and_nothing_changes(world, role):
    with pytest.raises(Forbidden):
        update(world, role, name="Hacked")
    assert world.org_service.get_current(context(world)).name == "Acme Sales"


def test_organization_field_rules(world):
    assert codes(lambda: update(world, name="A")) == {"name": ["VALIDATION_TOO_SHORT"]}
    assert codes(lambda: update(world, name="x" * 121)) == {"name": ["VALIDATION_TOO_LONG"]}
    assert codes(lambda: update(world, name="<x>")) == {"name": ["VALIDATION_MARKUP_NOT_ALLOWED"]}
    assert codes(lambda: update(world, timezone="Nope/Zone")) == {
        "timezone": ["VALIDATION_TIMEZONE_INVALID"]
    }


def test_an_empty_update_changes_and_audits_nothing(world):
    audited = len(world.audit.events)
    assert update(world).name == "Acme Sales"
    assert len(world.audit.events) == audited
