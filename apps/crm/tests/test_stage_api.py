"""Deal stage endpoints over HTTP on nudge_test: rules from API_CONTRACT (Q-5), roles, tenant
isolation and audit."""

import pytest
from django.db import connection
from rest_framework.test import APIClient

from apps.crm.tests.test_stages import insert_deal
from common.constants import Role
from common.tenancy import TenantContext
from config import container

pytestmark = pytest.mark.django_db

LIST = "/api/v1/deal-stages/"
ORDER = "/api/v1/deal-stages/order/"
DEFAULTS = ["New", "Contacted", "Meeting scheduled", "Proposal", "Negotiation", "Won", "Lost"]


def one(stage_id) -> str:
    return f"/api/v1/deal-stages/{stage_id}/"


@pytest.fixture
def org(tenancy):
    return tenancy.organization("Acme")


@pytest.fixture
def owner(tenancy, org):
    return tenancy.member(Role.OWNER, org)


def call(method: str, url: str, who, org_id=None, body=None):
    client = APIClient()
    return getattr(client, method)(url, body, format="json", **who.headers(org_id))


def names(response) -> list[str]:
    return [s["name"] for s in response.json()]


def stages(owner, org_id) -> list[dict]:
    return call("get", LIST, owner, org_id).json()


def audit_actions() -> list[str]:
    with connection.cursor() as cursor:
        cursor.execute("SELECT action FROM audit_logs")
        return [r[0] for r in cursor.fetchall()]


# ---- list


def test_any_member_lists_the_stages_in_order_with_deal_counts(tenancy, org, owner):
    member = tenancy.member(Role.MEMBER, org)
    response = call("get", LIST, member, org)
    assert response.status_code == 200 and names(response) == DEFAULTS
    first = response.json()[0]
    assert set(first) == {"id", "name", "position", "outcome", "deal_count"}
    assert [s["outcome"] for s in response.json()] == ["open"] * 5 + ["won", "lost"]
    assert [s["position"] for s in response.json()] == list(range(7))
    insert_deal(TenantContext(owner.user_id, org, Role.OWNER), first["id"], owner.user_id)
    assert stages(owner, org)[0]["deal_count"] == 1


def test_listing_needs_a_token_and_no_other_endpoint_is_public(org):
    assert APIClient().get(LIST).status_code == 401


# ---- create


def test_create_inserts_an_open_stage_before_won_and_audits_it(org, owner):
    response = call("post", LIST, owner, org, {"name": "  Demo   booked "})
    assert response.status_code == 201
    assert response.json()["name"] == "Demo booked" and response.json()["outcome"] == "open"
    assert response.json()["position"] == 5 and response.json()["deal_count"] == 0
    assert names(call("get", LIST, owner, org)) == [*DEFAULTS[:5], "Demo booked", "Won", "Lost"]
    assert [s["position"] for s in stages(owner, org)] == list(range(8))
    assert "deal_stage.create" in audit_actions()


def test_the_twelve_stage_limit(org, owner):
    for index in range(5):
        assert call("post", LIST, owner, org, {"name": f"Extra {index}"}).status_code == 201
    response = call("post", LIST, owner, org, {"name": "One too many"})
    assert response.status_code == 400 and response.json()["code"] == "CRM_STAGE_LIMIT_REACHED"
    assert len(stages(owner, org)) == 12


def test_a_duplicate_name_is_409_ignoring_case_and_spaces(org, owner):
    for name in ("new", "  NEW ", "Won"):
        response = call("post", LIST, owner, org, {"name": name})
        assert response.status_code == 409 and response.json()["code"] == "CRM_STAGE_NAME_TAKEN"


@pytest.mark.parametrize(
    "body, code",
    [
        ({}, "VALIDATION_REQUIRED"),
        ({"name": ""}, "VALIDATION_REQUIRED"),
        ({"name": None}, "VALIDATION_REQUIRED"),
        ({"name": 5}, "VALIDATION_INVALID_TYPE"),
        ({"name": "x" * 41}, "VALIDATION_TOO_LONG"),
        ({"name": "<b>"}, "VALIDATION_MARKUP_NOT_ALLOWED"),
    ],
)
def test_create_name_rules(org, owner, body, code):
    response = call("post", LIST, owner, org, body)
    assert response.status_code == 400
    assert response.json()["fields"]["name"][0]["code"] == code
    assert len(stages(owner, org)) == 7


def test_unknown_fields_are_refused(org, owner):
    response = call("post", LIST, owner, org, {"name": "Ok", "outcome": "won"})
    assert response.status_code == 400 and "outcome" in response.json()["fields"]


# ---- rename


def test_rename_an_open_stage(org, owner):
    target = stages(owner, org)[1]
    response = call("patch", one(target["id"]), owner, org, {"name": "Reached out"})
    assert response.status_code == 200 and response.json()["name"] == "Reached out"
    assert response.json()["id"] == target["id"] and "deal_stage.update" in audit_actions()


def test_renaming_only_the_case_is_allowed(org, owner):
    target = stages(owner, org)[0]
    assert call("patch", one(target["id"]), owner, org, {"name": "NEW"}).json()["name"] == "NEW"


def test_rename_to_a_taken_name_is_409(org, owner):
    target = stages(owner, org)[0]
    response = call("patch", one(target["id"]), owner, org, {"name": "contacted"})
    assert response.status_code == 409 and response.json()["code"] == "CRM_STAGE_NAME_TAKEN"


def test_won_and_lost_cannot_be_renamed(org, owner):
    won, lost = stages(owner, org)[5:]
    for stage in (won, lost):
        response = call("patch", one(stage["id"]), owner, org, {"name": "Closed"})
        assert response.status_code == 400 and response.json()["code"] == "CRM_STAGE_FIXED"
    assert names(call("get", LIST, owner, org))[5:] == ["Won", "Lost"]


# ---- reorder


def ids_of(owner, org) -> list[str]:
    return [s["id"] for s in stages(owner, org)]


def test_reorder_rewrites_positions_and_audits(org, owner):
    ids = ids_of(owner, org)
    new_order = [ids[0], ids[2], ids[1], ids[4], ids[3], ids[5], ids[6]]
    response = call("put", ORDER, owner, org, {"ids": new_order})
    assert response.status_code == 200
    assert [s["id"] for s in response.json()] == new_order
    assert [s["position"] for s in response.json()] == list(range(7))
    assert ids_of(owner, org) == new_order and "deal_stage.reorder" in audit_actions()


def test_the_same_order_changes_nothing_and_audits_nothing(org, owner):
    assert call("put", ORDER, owner, org, {"ids": ids_of(owner, org)}).status_code == 200
    assert "deal_stage.reorder" not in audit_actions()


@pytest.mark.parametrize(
    "build",
    [
        lambda ids: ids[:-1],  # a stage is missing
        lambda ids: [*ids, ids[0]],  # a stage twice
        lambda ids: [ids[1], ids[0], *ids[2:]],  # the first open stage moved
        lambda ids: [*ids[:5], ids[6], ids[5]],  # Lost before Won
        lambda ids: [*ids[:4], ids[5], ids[4], ids[6]],  # Won before an open stage
        lambda ids: [],
        lambda ids: [*ids[:6], "00000000-0000-0000-0000-000000000000"],  # unknown id
        lambda ids: [ids[0]] * 7,
    ],
)
def test_bad_orders_are_400_and_change_nothing(org, owner, build):
    before = ids_of(owner, org)
    response = call("put", ORDER, owner, org, {"ids": build(before)})
    assert response.status_code == 400
    assert response.json()["fields"]["ids"][0]["code"] == "CRM_STAGE_ORDER_INVALID"
    assert ids_of(owner, org) == before


@pytest.mark.parametrize(
    "body, code",
    [
        ({}, "VALIDATION_REQUIRED"),
        ({"ids": "abc"}, "VALIDATION_LIST_INVALID"),
        ({"ids": ["nope"]}, "VALIDATION_UUID_INVALID"),
        ({"ids": [5]}, "VALIDATION_UUID_INVALID"),
    ],
)
def test_order_input_shape(org, owner, body, code):
    response = call("put", ORDER, owner, org, body)
    assert response.status_code == 400
    assert response.json()["fields"]["ids"][0]["code"] == code


def test_another_organizations_stage_ids_cannot_be_smuggled_into_the_order(tenancy, org, owner):
    other = tenancy.organization("Other")
    foreign = tenancy.member(Role.OWNER, other)
    foreign_ids = ids_of(foreign, other)
    mixed = [*ids_of(owner, org)[:6], foreign_ids[6]]
    response = call("put", ORDER, owner, org, {"ids": mixed})
    assert response.status_code == 400
    assert ids_of(foreign, other) == foreign_ids


# ---- delete


def test_delete_an_open_stage_closes_the_gap_and_audits(org, owner):
    target = stages(owner, org)[2]
    response = call("delete", one(target["id"]), owner, org)
    assert response.status_code == 204 and response.content == b""
    after = stages(owner, org)
    assert [s["name"] for s in after] == [
        "New",
        "Contacted",
        "Proposal",
        "Negotiation",
        "Won",
        "Lost",
    ]
    assert [s["position"] for s in after] == list(range(6))
    assert "deal_stage.delete" in audit_actions()


def test_won_and_lost_cannot_be_deleted(org, owner):
    for stage in stages(owner, org)[5:]:
        response = call("delete", one(stage["id"]), owner, org)
        assert response.status_code == 400 and response.json()["code"] == "CRM_STAGE_FIXED"


def test_a_stage_with_deals_cannot_be_deleted_not_even_by_a_soft_deleted_deal(org, owner):
    context = TenantContext(owner.user_id, org, Role.OWNER)
    target = stages(owner, org)[1]
    insert_deal(context, target["id"], owner.user_id, "2026-01-01T00:00:00Z")
    response = call("delete", one(target["id"]), owner, org)
    assert response.status_code == 409 and response.json()["code"] == "CRM_STAGE_IN_USE"
    assert len(stages(owner, org)) == 7


def test_the_last_open_stage_cannot_be_deleted(org, owner):
    for stage in stages(owner, org)[1:5]:
        assert call("delete", one(stage["id"]), owner, org).status_code == 204
    last = stages(owner, org)[0]
    response = call("delete", one(last["id"]), owner, org)
    assert response.status_code == 409 and response.json()["code"] == "CRM_LAST_OPEN_STAGE"


def test_deleting_an_unknown_stage_is_404(org, owner):
    response = call("delete", one("00000000-0000-0000-0000-000000000000"), owner, org)
    assert response.status_code == 404 and response.json()["code"] == "COMMON_NOT_FOUND"


# ---- roles


@pytest.mark.parametrize("role", [Role.MANAGER, Role.MEMBER])
def test_manager_and_member_can_read_but_not_change(tenancy, org, owner, role):
    person = tenancy.member(role, org)
    target = stages(owner, org)[1]
    assert call("get", LIST, person, org).status_code == 200
    attempts = [
        call("post", LIST, person, org, {"name": "Sneaky"}),
        call("patch", one(target["id"]), person, org, {"name": "Sneaky"}),
        call("put", ORDER, person, org, {"ids": ids_of(owner, org)}),
        call("delete", one(target["id"]), person, org),
    ]
    assert [r.status_code for r in attempts] == [403, 403, 403, 403]
    assert all(r.json()["code"] == "COMMON_FORBIDDEN" for r in attempts)
    assert names(call("get", LIST, owner, org)) == DEFAULTS


def test_an_admin_can_change_stages(tenancy, org):
    admin = tenancy.member(Role.ADMIN, org)
    assert call("post", LIST, admin, org, {"name": "Admin stage"}).status_code == 201


def test_the_role_is_checked_before_the_body(tenancy, org):
    member = tenancy.member(Role.MEMBER, org)
    assert call("post", LIST, member, org, {"bad": 1}).status_code == 403


# ---- tenancy


def test_another_organizations_stage_is_404_for_every_write(tenancy, org, owner):
    other = tenancy.organization("Other")
    stranger = tenancy.member(Role.OWNER, other)
    target = stages(owner, org)[1]
    results = [
        call("patch", one(target["id"]), stranger, other, {"name": "Mine now"}),
        call("delete", one(target["id"]), stranger, other),
    ]
    assert [r.status_code for r in results] == [404, 404]
    assert names(call("get", LIST, owner, org)) == DEFAULTS


def test_a_user_cannot_name_an_organization_they_do_not_belong_to(tenancy, org, owner):
    other = tenancy.organization("Other")
    for method, url, body in (
        ("get", LIST, None),
        ("post", LIST, {"name": "X"}),
        ("put", ORDER, {"ids": []}),
    ):
        response = call(method, url, owner, other, body)
        assert response.status_code == 404 and response.json()["code"] == "COMMON_NOT_FOUND"
    assert call("get", LIST, tenancy.member(Role.OWNER, other), other).status_code == 200
    assert len(stages(tenancy.member(Role.OWNER, other), other)) == 7


def test_two_memberships_need_a_header_and_the_header_decides_the_role(tenancy, org, owner):
    second = tenancy.organization("Second")
    tenancy.join(owner, second, Role.MEMBER)
    no_header = call("get", LIST, owner)
    assert (
        no_header.status_code == 400 and no_header.json()["code"] == "TENANCY_ORGANIZATION_REQUIRED"
    )
    assert call("post", LIST, owner, org, {"name": "Where I own"}).status_code == 201
    assert call("post", LIST, owner, second, {"name": "Where I am a member"}).status_code == 403
    assert "Where I own" not in names(call("get", LIST, owner, second))


def test_a_removed_member_is_stopped_on_the_next_request(tenancy, org, owner):
    admin = tenancy.member(Role.ADMIN, org)
    assert call("get", LIST, admin, org).status_code == 200
    with connection.cursor() as cursor:
        cursor.execute("UPDATE memberships SET status = 3 WHERE user_id = %s", [admin.user_id])
    assert call("get", LIST, admin, org).status_code == 404


def test_a_demoted_admin_loses_write_access_at_once(tenancy, org):
    admin = tenancy.member(Role.ADMIN, org)
    assert call("post", LIST, admin, org, {"name": "Before"}).status_code == 201
    with connection.cursor() as cursor:
        cursor.execute("UPDATE memberships SET role = 4 WHERE user_id = %s", [admin.user_id])
    assert call("post", LIST, admin, org, {"name": "After"}).status_code == 403


def test_a_malformed_header_is_404(org, owner):
    for bad in ("", "not-a-uuid"):
        response = APIClient().get(LIST, **{**owner.headers(), "HTTP_X_ORGANIZATION_ID": bad})
        assert response.status_code == 404


def test_the_container_builds_the_stage_service_for_real(org):
    assert container.stage_service() is not None
