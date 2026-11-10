"""PATCH /auth/me/ and GET/PATCH /organizations/current/ over HTTP, with tenant checks."""

import json

import pytest
from django.db import connection
from rest_framework.test import APIClient

from common.constants import Role

pytestmark = pytest.mark.django_db

ME = "/api/v1/auth/me/"
CURRENT = "/api/v1/organizations/current/"


def call(method: str, url: str, who, org_id=None, body=None):
    return getattr(APIClient(), method)(url, body, format="json", **who.headers(org_id))


def audit_rows(action: str) -> list[tuple]:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT organization_id, details FROM audit_logs WHERE action = %s", [action]
        )
        return cursor.fetchall()


@pytest.fixture
def org(tenancy):
    return tenancy.organization("Acme")


@pytest.fixture
def owner(tenancy, org):
    return tenancy.member(Role.OWNER, org)


# ---- PATCH /auth/me/


def test_patch_me_changes_only_what_was_sent_and_returns_the_user(org, owner):
    before = call("get", ME, owner).json()
    response = call(
        "patch",
        ME,
        owner,
        None,
        {
            "name": "New Name",
            "phone": "+92 300 1234567",
            "quiet_hours_start": "22:00",
            "quiet_hours_end": "07:30",
        },
    )
    body = response.json()
    assert response.status_code == 200
    assert (body["name"], body["phone"]) == ("New Name", "+923001234567")
    assert (body["quiet_hours_start"], body["quiet_hours_end"]) == ("22:00", "07:30")
    assert body["timezone"] == before["timezone"] and body["email"] == before["email"]
    assert call("get", ME, owner).json() == body


def test_patch_me_clears_phone_and_quiet_hours_with_null(org, owner):
    call(
        "patch",
        ME,
        owner,
        None,
        {"phone": "+923001234567", "quiet_hours_start": "22:00", "quiet_hours_end": "07:00"},
    )
    body = call(
        "patch",
        ME,
        owner,
        None,
        {"phone": None, "quiet_hours_start": None, "quiet_hours_end": None},
    ).json()
    assert body["phone"] is None and body["quiet_hours_start"] is None


def test_patch_me_refuses_the_email_and_anything_unknown(org, owner):
    for body in ({"email": "x@y.com"}, {"role": "owner"}, {"id": "1"}, {"password": "x"}):
        response = call("patch", ME, owner, None, body)
        assert response.status_code == 400
        assert set(response.json()["fields"]) == set(body)


def test_patch_me_field_errors_and_nothing_is_written(org, owner):
    before = call("get", ME, owner).json()
    response = call(
        "patch", ME, owner, None, {"name": "Fine Name", "phone": "0300", "quiet_hours_start": "9"}
    )
    assert response.status_code == 400
    assert set(response.json()["fields"]) == {"phone", "quiet_hours_start"}
    assert call("get", ME, owner).json() == before


def test_patch_me_needs_a_token(org):
    assert APIClient().patch(ME, {"name": "Nope Nope"}, format="json").status_code == 401


def test_patch_me_is_audited_without_values(org, owner):
    call("patch", ME, owner, None, {"name": "Audited Name", "phone": "+923001234567"})
    ((org_id, details),) = audit_rows("user.profile_update")
    details = json.loads(details) if isinstance(details, str) else details
    assert str(org_id) == str(org) and details == {"fields": ["full_name", "phone"]}
    assert "Audited" not in str(details) and "+92" not in str(details)


def test_me_follows_x_organization_id_and_rejects_a_foreign_one(tenancy, org, owner):
    second = tenancy.organization("Second")
    tenancy.join(owner, second, Role.MEMBER)
    assert call("get", ME, owner).json()["organization"]["name"] == "Acme"
    chosen = call("get", ME, owner, second).json()
    assert (chosen["organization"]["name"], chosen["role"]) == ("Second", "member")
    assert len(chosen["organizations"]) == 2
    stranger_org = tenancy.organization("Stranger")
    assert call("get", ME, owner, stranger_org).status_code == 404


# ---- /organizations/current/


def test_any_member_reads_the_current_organization(tenancy, org):
    member = tenancy.member(Role.MEMBER, org)
    response = call("get", CURRENT, member, org)
    assert response.status_code == 200
    assert response.json() == {
        "id": str(org),
        "name": "Acme",
        "type": "business",
        "timezone": "UTC",
        "automation_paused": False,
    }


def test_the_only_membership_is_used_without_a_header(tenancy, org):
    member = tenancy.member(Role.MEMBER, org)
    assert call("get", CURRENT, member).json()["id"] == str(org)


@pytest.mark.parametrize("role", [Role.OWNER, Role.ADMIN])
def test_owner_and_admin_edit_the_organization_and_it_is_audited(tenancy, org, role):
    person = tenancy.member(role, org)
    response = call(
        "patch", CURRENT, person, org, {"name": "  Renamed  Co ", "timezone": "Asia/Karachi"}
    )
    assert response.status_code == 200
    assert (response.json()["name"], response.json()["timezone"]) == ("Renamed Co", "Asia/Karachi")
    assert call("get", CURRENT, person, org).json() == response.json()
    ((org_id, _),) = audit_rows("organization.update")
    assert str(org_id) == str(org)


@pytest.mark.parametrize("role", [Role.MANAGER, Role.MEMBER])
def test_manager_and_member_cannot_edit(tenancy, org, role):
    person = tenancy.member(role, org)
    response = call("patch", CURRENT, person, org, {"name": "Hacked"})
    assert response.status_code == 403 and response.json()["code"] == "COMMON_FORBIDDEN"
    assert call("get", CURRENT, person, org).json()["name"] == "Acme"
    assert audit_rows("organization.update") == []


def test_organization_field_errors(tenancy, org, owner):
    for body, field in (
        ({"name": "A"}, "name"),
        ({"name": "<b>"}, "name"),
        ({"name": None}, "name"),
        ({"timezone": "Nope/Zone"}, "timezone"),
        ({"currency": "USD"}, "currency"),
        ({"automation_paused": True}, "automation_paused"),
    ):
        response = call("patch", CURRENT, owner, org, body)
        assert response.status_code == 400 and field in response.json()["fields"]


def test_one_organization_cannot_read_or_edit_another(tenancy, org, owner):
    other = tenancy.organization("Other")
    stranger = tenancy.member(Role.OWNER, other, "Stranger")
    assert call("get", CURRENT, owner, other).status_code == 404
    assert call("patch", CURRENT, owner, other, {"name": "Taken Over"}).status_code == 404
    assert call("get", CURRENT, stranger, other).json()["name"] == "Other"
    assert call("get", CURRENT, owner, org).json()["name"] == "Acme"


def test_a_member_of_two_organizations_is_an_admin_only_where_they_are(tenancy, org, owner):
    second = tenancy.organization("Second")
    tenancy.join(owner, second, Role.MEMBER)
    assert call("patch", CURRENT, owner, org, {"name": "Edited Acme"}).status_code == 200
    assert call("patch", CURRENT, owner, second, {"name": "Edited Second"}).status_code == 403
    assert call("get", CURRENT, owner).status_code == 400
