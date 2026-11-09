"""TenantService: X-Organization-ID (or the only membership) -> TenantContext, from the database."""

from dataclasses import replace
from uuid import UUID, uuid4

import pytest

from apps.accounts.domain.enums import MembershipStatus
from apps.accounts.tests.fakes import AccountsWorld
from common.constants import AccountType, Role
from common.errors import NotFound, ValidationFailed
from common.tenancy import TenantContext


@pytest.fixture
def world() -> AccountsWorld:
    w = AccountsWorld()
    w.verified_user()
    return w


def my_id(world: AccountsWorld) -> UUID:
    return world.users.get_by_email("ali@example.com").id


def my_org(world: AccountsWorld) -> UUID:
    return world.memberships.list_active_for_user(my_id(world))[0].organization.id


def join_another(world: AccountsWorld, role: Role = Role.MEMBER, name: str = "Second Co") -> UUID:
    organization = world.organizations.create(
        organization_id=world.ids.new_id(),
        name=name,
        account_type=AccountType.BUSINESS,
        timezone="UTC",
    )
    world.memberships.create(
        membership_id=world.ids.new_id(),
        organization_id=organization.id,
        user_id=my_id(world),
        role=role,
    )
    return organization.id


def resolve(world: AccountsWorld, header: str | None) -> TenantContext:
    return world.tenant.resolve(user_id=my_id(world), organization_header=header)


def test_without_a_header_the_only_membership_is_used(world):
    context = resolve(world, None)
    assert context == TenantContext(my_id(world), my_org(world), Role.OWNER)


def test_with_two_memberships_and_no_header_the_caller_must_choose(world):
    join_another(world)
    with pytest.raises(ValidationFailed) as info:
        resolve(world, None)
    assert info.value.code == "TENANCY_ORGANIZATION_REQUIRED" and info.value.status == 400


def test_the_header_picks_the_organization_and_the_role_comes_from_that_membership(world):
    first, second = my_org(world), join_another(world, Role.MEMBER)
    assert resolve(world, str(second)) == TenantContext(my_id(world), second, Role.MEMBER)
    assert resolve(world, str(first)).role is Role.OWNER


def test_the_header_is_accepted_in_capitals_too(world):
    join_another(world)
    assert resolve(world, str(my_org(world)).upper()).organization_id == my_org(world)


def test_an_organization_the_user_does_not_belong_to_is_404_not_403(world):
    with pytest.raises(NotFound):
        resolve(world, str(uuid4()))


def test_another_users_organization_is_404(world):
    other = world.verified_user(email="other@example.com", name="Sana Malik")
    foreign = other.me.current.organization.id
    with pytest.raises(NotFound):
        resolve(world, str(foreign))


@pytest.mark.parametrize("header", ["", " ", "not-a-uuid", "1", "x" * 500, "{" + "0" * 36 + "}"])
def test_a_malformed_header_is_404(world, header):
    with pytest.raises(NotFound):
        resolve(world, header)


def test_a_suspended_or_removed_membership_cannot_be_used(world):
    second = join_another(world)
    for status in (MembershipStatus.SUSPENDED, MembershipStatus.REMOVED):
        rows = world.memberships.rows
        index = next(i for i, m in enumerate(rows) if m.organization_id == second)
        rows[index] = replace(rows[index], status=status)
        with pytest.raises(NotFound):
            resolve(world, str(second))


def test_a_demotion_applies_on_the_very_next_request(world):
    second = join_another(world, Role.ADMIN)
    assert resolve(world, str(second)).role is Role.ADMIN
    rows = world.memberships.rows
    index = next(i for i, m in enumerate(rows) if m.organization_id == second)
    rows[index] = replace(rows[index], role=Role.MEMBER)
    assert resolve(world, str(second)).role is Role.MEMBER


def test_a_user_without_any_membership_is_404(world):
    world.memberships.rows.clear()
    with pytest.raises(NotFound):
        resolve(world, None)


def test_me_follows_the_header_and_defaults_to_the_oldest(world):
    first, second = my_org(world), join_another(world)
    assert world.me_service.get_me(my_id(world)).current.organization.id == first
    chosen = world.me_service.get_me(my_id(world), str(second))
    assert chosen.current.organization.id == second and len(chosen.organizations) == 2
    with pytest.raises(NotFound):
        world.me_service.get_me(my_id(world), str(uuid4()))
