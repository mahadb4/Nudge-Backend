"""accounts repositories on the real test database, with tenant isolation and query counts."""

from datetime import timedelta
from uuid import UUID

import pytest
from django.db import IntegrityError

from apps.accounts.domain.enums import MembershipStatus
from apps.accounts.domain.errors import DuplicateEmail
from apps.accounts.repositories.models import MembershipModel, OrganizationModel
from apps.accounts.tests.conftest import NOW
from common.constants import AccountType, Role

pytestmark = pytest.mark.django_db


# ---- users


def test_create_and_read_back_a_user(users, make_user):
    created = make_user()
    assert created.email == "ali@example.com" and created.full_name == "Ali Raza"
    assert (
        created.password_hash == "argon2$fake"
    )  # stored exactly as given: hashing is the service's job
    assert (
        created.is_active is True
        and created.email_verified_at is None
        and created.last_login is None
    )
    assert (
        created.created_at is not None
    )  # filled by the database default and returned by the insert
    assert users.get(created.id) == created
    assert users.get_by_email("ali@example.com") == created


def test_missing_users_are_none(users):
    assert users.get(UUID(int=1)) is None
    assert users.get_by_email("nobody@example.com") is None
    assert users.email_exists("nobody@example.com") is False


def test_email_exists(users, make_user):
    make_user()
    assert users.email_exists("ali@example.com") is True


def test_a_duplicate_email_raises_and_leaves_the_transaction_usable(users, make_user, ids):
    make_user()
    with pytest.raises(DuplicateEmail):
        users.create(
            user_id=ids.new_id(),
            email="ali@example.com",
            password_hash="x",
            full_name="Other",
            timezone="UTC",
        )
    assert (
        users.email_exists("ali@example.com") is True
    )  # the surrounding transaction was not poisoned


def test_an_upper_case_email_is_a_bug_not_a_duplicate(users, ids):
    """The database requires lower case (ck_users_email). The services normalise first."""
    with pytest.raises(IntegrityError):
        users.create(
            user_id=ids.new_id(),
            email="ALI@example.com",
            password_hash="x",
            full_name="Ali",
            timezone="UTC",
        )


def test_mark_email_verified_works_once(users, make_user):
    user = make_user()
    assert users.mark_email_verified(user.id, NOW) is True
    assert users.mark_email_verified(user.id, NOW + timedelta(hours=1)) is False
    assert users.get(user.id).email_verified_at == NOW


def test_replace_registration_overwrites_an_unverified_user_only(users, make_user):
    user = make_user()
    assert users.replace_registration(
        user_id=user.id, password_hash="argon2$second", full_name="Second Name", timezone="UTC"
    )
    fresh = users.get(user.id)
    assert (fresh.password_hash, fresh.full_name, fresh.timezone) == (
        "argon2$second",
        "Second Name",
        "UTC",
    )
    users.mark_email_verified(user.id, NOW)
    assert not users.replace_registration(
        user_id=user.id, password_hash="argon2$third", full_name="Third", timezone="UTC"
    )
    assert users.get(user.id).password_hash == "argon2$second"


def test_update_profile_changes_only_the_named_organization(organizations, make_organization):
    first, other = make_organization(), make_organization()
    organizations.update_profile(
        organization_id=first.id,
        name="Renamed",
        account_type=AccountType.INDIVIDUAL,
        timezone="UTC",
    )
    assert organizations.get(first.id).name == "Renamed"
    assert organizations.get(first.id).account_type is AccountType.INDIVIDUAL
    assert organizations.get(other.id).name == other.name


def test_set_password_and_last_login(users, make_user):
    user = make_user()
    users.set_password(user.id, "argon2$new")
    users.touch_last_login(user.id, NOW)
    fresh = users.get(user.id)
    assert fresh.password_hash == "argon2$new" and fresh.last_login == NOW


def test_unicode_names_round_trip(users, make_user):
    assert (
        users.get(make_user("x@example.com", "李雷 O'Brien José").id).full_name
        == "李雷 O'Brien José"
    )


# ---- organizations


def test_organization_round_trip_for_both_account_types(organizations, make_organization):
    business = make_organization("Acme Sales", AccountType.BUSINESS)
    individual = make_organization("Ali Raza", AccountType.INDIVIDUAL)
    assert (
        organizations.get(business.id) == business and business.account_type is AccountType.BUSINESS
    )
    assert organizations.get(individual.id).account_type is AccountType.INDIVIDUAL
    assert business.created_at is not None


def test_a_closed_organization_is_not_returned(organizations, make_organization):
    org = make_organization()
    OrganizationModel.objects.filter(id=org.id).update(deactivated_at=NOW)
    assert organizations.get(org.id) is None


# ---- memberships


def test_create_a_membership_and_find_it_only_in_its_own_organization(
    memberships, make_user, make_organization, make_membership
):
    user, org_a, org_b = make_user(), make_organization("A"), make_organization("B")
    membership = make_membership(org_a.id, user.id, Role.OWNER)
    assert membership.role is Role.OWNER and membership.status is MembershipStatus.ACTIVE
    assert memberships.get_active(org_a.id, user.id) == membership
    assert (
        memberships.get_active(org_b.id, user.id) is None
    )  # tenant isolation: another organization finds nothing


def test_a_removed_or_suspended_member_is_not_active(
    memberships, make_user, make_organization, make_membership
):
    user, org = make_user(), make_organization()
    membership = make_membership(org.id, user.id, Role.MEMBER)
    for status in (MembershipStatus.SUSPENDED, MembershipStatus.REMOVED):
        MembershipModel.objects.filter(id=membership.id).update(status=int(status))
        assert memberships.get_active(org.id, user.id) is None


def test_list_active_for_user_is_oldest_first_and_skips_closed_organizations(
    memberships, make_user, make_organization, make_membership
):
    user = make_user()
    first, second, closed = (
        make_organization("First"),
        make_organization("Second"),
        make_organization("Closed"),
    )
    # Inside one test transaction now() is the same for every row, so give them distinct ages.
    for age, (org, role) in enumerate(
        [(first, Role.OWNER), (second, Role.MEMBER), (closed, Role.ADMIN)]
    ):
        made = make_membership(org.id, user.id, role)
        MembershipModel.objects.filter(id=made.id).update(created_at=NOW + timedelta(seconds=age))
    OrganizationModel.objects.filter(id=closed.id).update(deactivated_at=NOW)
    found = memberships.list_active_for_user(user.id)
    assert [(item.organization.name, item.membership.role) for item in found] == [
        ("First", Role.OWNER),
        ("Second", Role.MEMBER),
    ]


def test_list_active_for_user_uses_two_queries_however_many_organizations(
    memberships, make_user, make_organization, make_membership, django_assert_num_queries
):
    user = make_user()
    for index in range(5):
        make_membership(make_organization(f"Org {index}").id, user.id)
    with django_assert_num_queries(2):
        assert len(memberships.list_active_for_user(user.id)) == 5


def test_other_users_memberships_are_not_listed(
    memberships, make_user, make_organization, make_membership
):
    ali, sara = make_user("ali@example.com"), make_user("sara@example.com", "Sara Ali")
    make_membership(make_organization("Ali's").id, ali.id)
    assert memberships.list_active_for_user(sara.id) == []


# ---- sessions


def new_session(sessions, ids, user, **overrides):
    values = dict(
        session_id=ids.new_id(),
        user_id=user.id,
        refresh_token_hash="a" * 64,
        device_name="Chrome on Windows",
        ip_address="203.0.113.9",
        expires_at=NOW + timedelta(days=1),
    )
    return sessions.create(**{**values, **overrides})


def test_create_and_get_a_session(sessions, ids, make_user):
    user = make_user()
    session = new_session(sessions, ids, user)
    assert sessions.get(session.id) == session
    assert (session.device_name, session.ip_address, session.revoked_at) == (
        "Chrome on Windows",
        "203.0.113.9",
        None,
    )
    assert sessions.get_active(session.id, NOW) == session


def test_a_session_without_device_or_ip(sessions, ids, make_user):
    session = new_session(sessions, ids, make_user(), device_name=None, ip_address=None)
    assert (session.device_name, session.ip_address) == (None, None)


def test_an_expired_session_is_not_active_but_can_still_be_read(sessions, ids, make_user):
    session = new_session(sessions, ids, make_user())
    assert sessions.get_active(session.id, NOW + timedelta(days=1)) is None
    assert sessions.get(session.id) is not None


def test_rotate_replaces_the_hash_only_when_the_old_one_matches(sessions, ids, make_user):
    session = new_session(sessions, ids, make_user())
    assert (
        sessions.rotate(session_id=session.id, old_hash="b" * 64, new_hash="c" * 64, now=NOW)
        is False
    )
    assert (
        sessions.rotate(session_id=session.id, old_hash="a" * 64, new_hash="c" * 64, now=NOW)
        is True
    )
    assert (
        sessions.rotate(session_id=session.id, old_hash="a" * 64, new_hash="d" * 64, now=NOW)
        is False
    )  # replay
    fresh = sessions.get(session.id)
    assert fresh.refresh_token_hash == "c" * 64 and fresh.last_used_at == NOW


def test_rotate_is_refused_for_revoked_and_expired_sessions(sessions, ids, make_user):
    revoked = new_session(sessions, ids, make_user())
    sessions.revoke(revoked.id, NOW)
    assert (
        sessions.rotate(session_id=revoked.id, old_hash="a" * 64, new_hash="c" * 64, now=NOW)
        is False
    )
    user = make_user("sara@example.com", "Sara Ali")
    expired = new_session(sessions, ids, user, refresh_token_hash="e" * 64)
    assert (
        sessions.rotate(
            session_id=expired.id, old_hash="e" * 64, new_hash="f" * 64, now=NOW + timedelta(days=2)
        )
        is False
    )


def test_revoke_works_once(sessions, ids, make_user):
    session = new_session(sessions, ids, make_user())
    assert sessions.revoke(session.id, NOW) is True
    assert sessions.revoke(session.id, NOW) is False
    assert sessions.get_active(session.id, NOW) is None


def test_revoke_all_can_keep_the_current_session(sessions, ids, make_user):
    user, other = make_user(), make_user("sara@example.com", "Sara Ali")
    keep = new_session(sessions, ids, user, refresh_token_hash="1" * 64)
    drop = new_session(sessions, ids, user, refresh_token_hash="2" * 64)
    theirs = new_session(sessions, ids, other, refresh_token_hash="3" * 64)
    assert sessions.revoke_all(user.id, NOW, except_session_id=keep.id) == 1
    assert sessions.get_active(keep.id, NOW) and not sessions.get_active(drop.id, NOW)
    assert sessions.get_active(theirs.id, NOW)  # another user's session is untouched
    assert sessions.revoke_all(user.id, NOW) == 1


def test_two_sessions_cannot_share_a_refresh_hash(sessions, ids, make_user):
    user = make_user()
    new_session(sessions, ids, user)
    with pytest.raises(IntegrityError):
        new_session(sessions, ids, user)
