"""Contact endpoints over HTTP on nudge_test: rules, visibility, optimistic concurrency, audit,
query counts and tenant isolation for every endpoint."""

import json

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from apps.crm.repositories.contact_repository import PostgresContactRepository
from common.constants import Role
from common.pagination import parse_list_query
from common.tenancy import TenantContext

pytestmark = pytest.mark.django_db

LIST = "/api/v1/contacts/"
COMPANIES = "/api/v1/companies/"


def one(contact_id) -> str:
    return f"{LIST}{contact_id}/"


def call(method: str, url: str, who, org_id=None, body=None):
    return getattr(APIClient(), method)(url, body, format="json", **who.headers(org_id))


def sql(statement: str, params: list | None = None) -> list[tuple]:
    with connection.cursor() as cursor:
        cursor.execute(statement, params or [])
        return cursor.fetchall() if cursor.description else []


@pytest.fixture
def org(tenancy):
    return tenancy.organization("Acme")


@pytest.fixture
def owner(tenancy, org):
    return tenancy.member(Role.OWNER, org)


@pytest.fixture
def member(tenancy, org):
    return tenancy.member(Role.MEMBER, org)


def make(who, org_id, first="Ada", email=None, **extra) -> dict:
    email = email or f"{first.lower()}{abs(hash((first, str(extra)))) % 10**6}@example.com"
    response = call("post", LIST, who, org_id, {"first_name": first, "email": email, **extra})
    assert response.status_code == 201, response.json()
    return response.json()


def company(who, org_id, name="Acme Corp", **extra) -> dict:
    response = call("post", COMPANIES, who, org_id, {"name": name, **extra})
    assert response.status_code == 201, response.json()
    return response.json()


def names(response) -> list[str]:
    return [c["name"] for c in response.json()["results"]]


def audit(action: str) -> list[dict]:
    rows = sql("SELECT details FROM audit_logs WHERE action = %s", [action])
    return [json.loads(r[0]) if isinstance(r[0], str) else r[0] for r in rows]


def team_with(org_id, *people, name="Sales"):
    (team_id,) = sql(
        "INSERT INTO teams (organization_id, name) VALUES (%s, %s) RETURNING id", [org_id, name]
    )[0]
    for person in people:
        sql(
            "INSERT INTO team_members (organization_id, team_id, membership_id) "
            "SELECT %s, %s, id FROM memberships WHERE user_id = %s AND organization_id = %s",
            [org_id, team_id, person.user_id, org_id],
        )
    return team_id


# ---- create


def test_create_returns_201_with_defaults_and_the_full_shape(org, owner):
    acme = company(owner, org)
    created = make(
        owner,
        org,
        "  Grace ",
        last_name=" Hopper ",
        email="GRACE@Example.com",
        title=" CEO ",
        phone="+92 300 1234567",
        company_id=acme["id"],
    )
    assert (created["first_name"], created["last_name"], created["name"]) == (
        "Grace",
        "Hopper",
        "Grace Hopper",
    )
    assert (created["email"], created["phone"], created["title"]) == (
        "grace@example.com",
        "+923001234567",
        "CEO",
    )
    assert created["company"] == {"id": acme["id"], "name": "Acme Corp"}
    assert created["owner"] == {"id": str(owner.user_id), "name": "Person Tester"}
    assert created["visibility"] == "organization" and created["team_id"] is None
    assert (created["status"], created["opted_out_at"], created["source"]) == (
        "active",
        None,
        "manual",
    )
    assert created["last_contact_at"] is None
    assert set(created) == {
        "id",
        "first_name",
        "last_name",
        "name",
        "email",
        "phone",
        "title",
        "company",
        "owner",
        "visibility",
        "team_id",
        "status",
        "opted_out_at",
        "source",
        "last_contact_at",
        "created_at",
        "updated_at",
    }


def test_a_contact_without_company_or_last_name(org, owner):
    created = make(owner, org, "Solo")
    assert (created["company"], created["last_name"], created["name"]) == (None, None, "Solo")


def test_create_is_audited_with_the_label_only(org, owner):
    make(owner, org, "Audit", last_name="Me")
    assert audit("contact.create") == [{"label": "Audit Me", "changes": {}}]


@pytest.mark.parametrize(
    "body, field, code",
    [
        ({"email": "a@b.com"}, "first_name", "VALIDATION_REQUIRED"),
        ({"first_name": "Ada"}, "email", "VALIDATION_REQUIRED"),
        ({"first_name": "", "email": "a@b.com"}, "first_name", "VALIDATION_REQUIRED"),
        ({"first_name": "x" * 81, "email": "a@b.com"}, "first_name", "VALIDATION_TOO_LONG"),
        ({"first_name": "<b>", "email": "a@b.com"}, "first_name", "VALIDATION_MARKUP_NOT_ALLOWED"),
        ({"first_name": "1234", "email": "a@b.com"}, "first_name", "VALIDATION_NAME_NEEDS_LETTER"),
        (
            {"first_name": "Ada", "last_name": "<x>", "email": "a@b.com"},
            "last_name",
            "VALIDATION_MARKUP_NOT_ALLOWED",
        ),
        (
            {"first_name": "Ada", "last_name": "99", "email": "a@b.com"},
            "last_name",
            "VALIDATION_NAME_NEEDS_LETTER",
        ),
        ({"first_name": "Ada", "email": "not-an-email"}, "email", "VALIDATION_EMAIL_INVALID"),
        ({"first_name": "Ada", "email": None}, "email", "VALIDATION_REQUIRED"),
        (
            {"first_name": "Ada", "email": "a@b.com", "phone": "0300"},
            "phone",
            "VALIDATION_PHONE_NEEDS_PLUS",
        ),
        (
            {"first_name": "Ada", "email": "a@b.com", "phone": "+1"},
            "phone",
            "VALIDATION_PHONE_INVALID",
        ),
        (
            {"first_name": "Ada", "email": "a@b.com", "title": "x" * 81},
            "title",
            "VALIDATION_TOO_LONG",
        ),
        (
            {"first_name": "Ada", "email": "a@b.com", "company_id": "nope"},
            "company_id",
            "VALIDATION_UUID_INVALID",
        ),
        (
            {"first_name": "Ada", "email": "a@b.com", "visibility": "secret"},
            "visibility",
            "VALIDATION_CHOICE_INVALID",
        ),
    ],
)
def test_create_field_rules(org, owner, body, field, code):
    response = call("post", LIST, owner, org, body)
    assert response.status_code == 400
    assert response.json()["fields"][field][0]["code"] == code
    assert names(call("get", LIST, owner, org)) == []


@pytest.mark.parametrize(
    "field", ["id", "name", "source", "status", "opted_out_at", "organization_id", "company"]
)
def test_the_client_cannot_set_server_or_derived_fields(org, owner, field):
    response = call("post", LIST, owner, org, {"first_name": "Ada", "email": "a@b.com", field: "x"})
    assert response.status_code == 400 and field in response.json()["fields"]


def test_a_blank_last_name_phone_and_title_mean_none(org, owner):
    created = make(owner, org, "Blank", last_name="", phone="", title="  ")
    assert (created["last_name"], created["phone"], created["title"]) == (None, None, None)


def test_a_duplicate_email_is_409_and_names_the_existing_contact_if_visible(org, owner, member):
    first = make(owner, org, "First", email="dup@example.com")
    for email in ("dup@example.com", "DUP@example.com"):
        response = call("post", LIST, member, org, {"first_name": "Second", "email": email})
        assert response.status_code == 409 and response.json()["code"] == "CRM_CONTACT_EMAIL_TAKEN"
        assert response.json()["existing"] == {"id": first["id"], "name": "First"}


def test_a_duplicate_of_a_private_contact_does_not_reveal_it(org, owner, member):
    make(owner, org, "Hidden", email="hidden@example.com", visibility="private")
    response = call(
        "post", LIST, member, org, {"first_name": "Probe", "email": "hidden@example.com"}
    )
    assert response.status_code == 409 and response.json()["code"] == "CRM_CONTACT_EMAIL_TAKEN"
    assert "existing" not in response.json()
    # An Owner may see it, so the same probe from an Owner names it.
    again = call("post", LIST, owner, org, {"first_name": "Probe", "email": "hidden@example.com"})
    assert again.json()["existing"]["name"] == "Hidden"


def test_a_deleted_contact_frees_its_email_and_other_organizations_may_reuse_it(
    tenancy, org, owner
):
    first = make(owner, org, "Gone", email="same@example.com")
    other = tenancy.organization("Other")
    make(tenancy.member(Role.OWNER, other), other, "Elsewhere", email="same@example.com")
    call("delete", one(first["id"]), owner, org)
    assert make(owner, org, "Back", email="same@example.com")["name"] == "Back"


def test_the_company_must_exist_in_this_organization_and_be_visible(tenancy, org, owner, member):
    other = tenancy.organization("Other")
    foreign = company(tenancy.member(Role.OWNER, other), other, "Foreign Co")
    private = company(owner, org, "Private Co", visibility="private")
    for who, company_id in (
        (owner, foreign["id"]),
        (member, private["id"]),
        (owner, "00000000-0000-0000-0000-000000000000"),
    ):
        response = call(
            "post",
            LIST,
            who,
            org,
            {"first_name": "Ada", "email": "x@y.com", "company_id": company_id},
        )
        assert response.status_code == 400
        assert response.json()["fields"]["company_id"][0]["code"] == "VALIDATION_COMPANY_INVALID"
    assert (
        call(
            "post",
            LIST,
            owner,
            org,
            {"first_name": "Ada", "email": "x@y.com", "company_id": private["id"]},
        ).status_code
        == 201
    )


def test_owner_and_team_rules_are_the_same_as_for_companies(tenancy, org, owner, member):
    team = team_with(org, member)
    outsider = tenancy.member(Role.MEMBER, org)
    other = tenancy.organization("Other")
    stranger = tenancy.member(Role.OWNER, other)
    base = {"first_name": "Ada", "email": "x@y.com"}
    bad = [
        (member, {"owner_id": str(stranger.user_id)}, "owner_id", "VALIDATION_MEMBER_INVALID"),
        (member, {"visibility": "team"}, "team_id", "VALIDATION_TEAM_REQUIRED"),
        (member, {"team_id": str(team)}, "team_id", "VALIDATION_TEAM_NOT_ALLOWED"),
        (
            outsider,
            {"visibility": "team", "team_id": str(team)},
            "team_id",
            "VALIDATION_TEAM_INVALID",
        ),
        (
            owner,
            {"visibility": "team", "team_id": str(team_with(other, stranger))},
            "team_id",
            "VALIDATION_TEAM_INVALID",
        ),
    ]
    for who, extra, field, code in bad:
        response = call("post", LIST, who, org, {**base, **extra})
        assert response.status_code == 400, extra
        assert response.json()["fields"][field][0]["code"] == code
    ok = call("post", LIST, member, org, {**base, "visibility": "team", "team_id": str(team)})
    assert ok.status_code == 201 and ok.json()["team_id"] == str(team)


# ---- visibility


def test_visibility_decides_who_sees_a_contact(tenancy, org, owner, member):
    team = team_with(org, member)
    outsider = tenancy.member(Role.MANAGER, org)
    make(owner, org, "Public")
    private = make(owner, org, "Private", visibility="private")
    teamed = make(owner, org, "Teamed", visibility="team", team_id=str(team))
    mine = make(member, org, "Mine", visibility="private")
    seen = {
        "owner": (owner, ["Mine", "Private", "Public", "Teamed"]),
        "member": (member, ["Mine", "Public", "Teamed"]),
        "outsider": (outsider, ["Public"]),
    }
    for who, expected in seen.values():
        response = call("get", LIST, who, org)
        assert names(response) == expected and response.json()["count"] == len(expected)
    assert call("get", one(private["id"]), outsider, org).status_code == 404
    assert call("get", one(teamed["id"]), outsider, org).status_code == 404
    assert call("get", one(teamed["id"]), member, org).status_code == 200
    assert call("get", one(mine["id"]), owner, org).status_code == 200
    for method, body in (
        ("patch", {"updated_at": private["updated_at"], "title": "Hijack"}),
        ("delete", None),
    ):
        assert call(method, one(private["id"]), outsider, org, body).status_code == 404


def test_a_private_company_name_is_not_shown_on_a_contact_the_caller_can_see(org, owner, member):
    secret = company(owner, org, "Secret Co", visibility="private")
    shown = make(owner, org, "Linked", company_id=secret["id"])
    assert call("get", one(shown["id"]), owner, org).json()["company"]["name"] == "Secret Co"
    assert call("get", one(shown["id"]), member, org).json()["company"] is None


# ---- list


def test_default_order_is_last_then_first_name_and_pages_have_links(org, owner):
    for first, last in (
        ("Zed", "Adams"),
        ("Amy", "baker"),
        ("Bob", "Adams"),
        ("Cy", "Chen"),
        ("Di", "Evans"),
    ):
        make(owner, org, first, last_name=last)
    page = call("get", LIST + "?page_size=2", owner, org).json()
    assert [c["name"] for c in page["results"]] == ["Bob Adams", "Zed Adams"] and page["count"] == 5
    assert page["previous"] is None and "page=2" in page["next"]
    second = call("get", LIST + "?page_size=2&page=2", owner, org).json()
    assert [c["name"] for c in second["results"]] == ["Amy baker", "Cy Chen"]
    assert call("get", LIST + "?page_size=2&page=9", owner, org).json()["results"] == []


def test_ordering_by_newest_first(org, owner):
    ids = [make(owner, org, name)["id"] for name in ("First", "Second", "Third")]
    for age, contact_id in enumerate(ids):
        sql(
            "UPDATE contacts SET created_at = now() + make_interval(secs => %s) WHERE id = %s",
            [age, contact_id],
        )
    assert names(call("get", LIST + "?ordering=-created_at", owner, org)) == [
        "Third",
        "Second",
        "First",
    ]


def test_search_covers_names_email_and_company_name_literally(org, owner):
    acme = company(owner, org, "Northwind Traders")
    make(owner, org, "Ada", last_name="Lovelace", email="ada@analytical.io")
    make(owner, org, "Grace", last_name="Hopper", email="grace@navy.mil", company_id=acme["id"])
    make(owner, org, "Per_cent", last_name="Abc%", email="pc@example.com")
    make(owner, org, "Perxcent", email="px@example.com")
    assert names(call("get", LIST + "?q=lovel", owner, org)) == ["Ada Lovelace"]
    assert names(call("get", LIST + "?q=NAVY.mil", owner, org)) == ["Grace Hopper"]
    assert names(call("get", LIST + "?q=northwind", owner, org)) == ["Grace Hopper"]
    assert names(call("get", LIST + "?q=r_c", owner, org)) == ["Per_cent Abc%"]
    assert names(call("get", LIST + "?q=c%25", owner, org)) == ["Per_cent Abc%"]
    assert names(call("get", LIST + "?q=nothing-here", owner, org)) == []


def test_filters_status_owner_and_company(org, owner, member):
    acme = company(owner, org, "Acme")
    a = make(owner, org, "Alpha", company_id=acme["id"])
    make(member, org, "Beta")
    sql("UPDATE contacts SET opted_out_at = now() WHERE id = %s", [a["id"]])
    assert names(call("get", LIST + "?status=opted_out", owner, org)) == ["Alpha"]
    assert names(call("get", LIST + "?status=active", owner, org)) == ["Beta"]
    assert names(call("get", LIST + f"?owner_id={member.user_id}", owner, org)) == ["Beta"]
    assert names(call("get", LIST + f"?company_id={acme['id']}", owner, org)) == ["Alpha"]
    assert call("get", one(a["id"]), owner, org).json()["status"] == "opted_out"


@pytest.mark.parametrize(
    "query, field, code",
    [
        ("?page=0", "page", "VALIDATION_PAGE_INVALID"),
        ("?page_size=101", "page_size", "VALIDATION_PAGE_SIZE_INVALID"),
        ("?ordering=email", "ordering", "VALIDATION_CHOICE_INVALID"),
        ("?q=a", "q", "VALIDATION_TOO_SHORT"),
        ("?status=suspended", "status", "VALIDATION_CHOICE_INVALID"),
        ("?owner_id=nope", "owner_id", "VALIDATION_UUID_INVALID"),
        ("?company_id=nope", "company_id", "VALIDATION_UUID_INVALID"),
        ("?team_id=1", "team_id", "VALIDATION_UNKNOWN_FIELD"),
    ],
)
def test_bad_query_parameters_name_the_parameter(org, owner, query, field, code):
    response = call("get", LIST + query, owner, org)
    assert response.status_code == 400
    assert response.json()["fields"][field][0]["code"] == code


def test_the_list_runs_a_fixed_number_of_queries_however_many_contacts(org, owner):
    repo = PostgresContactRepository()
    context = TenantContext(owner.user_id, org, Role.OWNER)
    query = parse_list_query({}, orderings=("name", "-created_at"), default_ordering="name")

    def run() -> int:
        with CaptureQueriesContext(connection) as queries:
            repo.list_page(context, query)
        return len(queries)

    for index in range(5):
        acme = company(owner, org, f"Company {index}")
        for person in range(3):
            make(owner, org, f"P{index}x{person}", last_name="Q", company_id=acme["id"])
    small = run()
    for index in range(20):
        make(owner, org, f"Extra{index:02d}", last_name="Z", company_id=acme["id"])
    assert run() == small <= 4


def test_the_list_endpoint_query_count_does_not_grow_with_the_page(org, owner):
    def api_queries() -> int:
        with CaptureQueriesContext(connection) as queries:
            assert call("get", LIST, owner, org).status_code == 200
        return len(queries)

    acme = company(owner, org, "Base Co")
    make(owner, org, "Seed", company_id=acme["id"])
    small = api_queries()
    for index in range(15):
        make(owner, org, f"More{index:02d}", company_id=acme["id"])
    assert api_queries() == small


# ---- get / update / delete


def test_get_one_returns_the_same_shape(org, owner):
    created = make(owner, org, "Get")
    assert call("get", one(created["id"]), owner, org).json() == created
    assert call("get", one("00000000-0000-0000-0000-000000000000"), owner, org).status_code == 404


def test_update_changes_only_what_was_sent_and_audits_without_personal_values(org, owner):
    created = make(owner, org, "Old", email="old@example.com", title="CTO")
    response = call(
        "patch",
        one(created["id"]),
        owner,
        org,
        {
            "updated_at": created["updated_at"],
            "first_name": "New",
            "title": None,
            "phone": "+923001234567",
        },
    )
    body = response.json()
    assert response.status_code == 200 and (body["first_name"], body["title"], body["phone"]) == (
        "New",
        None,
        "+923001234567",
    )
    assert body["email"] == "old@example.com" and body["updated_at"] > created["updated_at"]
    ((details),) = audit("contact.update")
    assert details["label"] == "Old"
    assert details["changes"] == {
        "first_name": "changed",
        "job_title": "changed",
        "phone": "changed",
    }
    assert "+92" not in json.dumps(details) and "CTO" not in json.dumps(details)


def test_update_company_owner_and_visibility(org, owner, member):
    one_co, two_co = company(owner, org, "One Co"), company(owner, org, "Two Co")
    created = make(owner, org, "Mover", company_id=one_co["id"])
    body = call(
        "patch",
        one(created["id"]),
        owner,
        org,
        {
            "updated_at": created["updated_at"],
            "company_id": two_co["id"],
            "owner_id": str(member.user_id),
            "visibility": "private",
        },
    ).json()
    assert (body["company"]["name"], body["owner"]["id"], body["visibility"]) == (
        "Two Co",
        str(member.user_id),
        "private",
    )
    cleared = call(
        "patch",
        one(created["id"]),
        owner,
        org,
        {"updated_at": body["updated_at"], "company_id": None},
    )
    assert cleared.json()["company"] is None


def test_email_cannot_be_cleared_and_must_stay_unique(org, owner):
    first = make(owner, org, "First", email="first@example.com")
    second = make(owner, org, "Second", email="second@example.com")
    cleared = call(
        "patch", one(second["id"]), owner, org, {"updated_at": second["updated_at"], "email": None}
    )
    assert (
        cleared.status_code == 400
        and cleared.json()["fields"]["email"][0]["code"] == "VALIDATION_REQUIRED"
    )
    clash = call(
        "patch",
        one(second["id"]),
        owner,
        org,
        {"updated_at": second["updated_at"], "email": "FIRST@example.com"},
    )
    assert clash.status_code == 409 and clash.json()["existing"] == {
        "id": first["id"],
        "name": "First",
    }
    same = call(
        "patch",
        one(first["id"]),
        owner,
        org,
        {"updated_at": first["updated_at"], "email": "FIRST@example.com"},
    )
    assert same.status_code == 200


def test_update_requires_updated_at(org, owner):
    created = make(owner, org, "Stamp")
    for body in (
        {"title": "X"},
        {"title": "X", "updated_at": None},
        {"title": "X", "updated_at": "yesterday"},
        {"title": "X", "updated_at": "2026-01-01T00:00:00"},
    ):
        response = call("patch", one(created["id"]), owner, org, body)
        assert response.status_code == 400 and "updated_at" in response.json()["fields"]


def test_a_stale_updated_at_is_409_with_the_current_contact(org, owner):
    created = make(owner, org, "Race")
    won = call(
        "patch",
        one(created["id"]),
        owner,
        org,
        {"updated_at": created["updated_at"], "title": "Won"},
    )
    assert won.status_code == 200
    stale = call(
        "patch",
        one(created["id"]),
        owner,
        org,
        {"updated_at": created["updated_at"], "title": "Lost"},
    )
    assert stale.status_code == 409 and stale.json()["code"] == "COMMON_VERSION_CONFLICT"
    assert stale.json()["current"]["title"] == "Won"
    fresh = call(
        "patch",
        one(created["id"]),
        owner,
        org,
        {"updated_at": won.json()["updated_at"], "title": "Third"},
    )
    assert fresh.status_code == 200


def test_an_update_that_changes_nothing_writes_nothing(org, owner):
    created = make(owner, org, "Same", email="same@example.com")
    response = call(
        "patch",
        one(created["id"]),
        owner,
        org,
        {"updated_at": created["updated_at"], "first_name": "Same", "email": "SAME@example.com"},
    )
    assert response.status_code == 200 and response.json()["updated_at"] == created["updated_at"]
    assert audit("contact.update") == []


def test_leaving_team_visibility_drops_the_team(org, member):
    team = team_with(org, member)
    created = make(member, org, "Team", visibility="team", team_id=str(team))
    back = call(
        "patch",
        one(created["id"]),
        member,
        org,
        {"updated_at": created["updated_at"], "visibility": "organization"},
    )
    assert back.status_code == 200 and back.json()["team_id"] is None


def test_delete_is_soft_audited_and_final(org, owner):
    created = make(owner, org, "Gone", last_name="Soon")
    other = make(owner, org, "Keeper")
    response = call("delete", one(created["id"]), owner, org)
    assert response.status_code == 204 and response.content == b""
    assert call("get", one(created["id"]), owner, org).status_code == 404
    assert names(call("get", LIST, owner, org)) == ["Keeper"]
    ((deleted_at,),) = sql("SELECT deleted_at FROM contacts WHERE id = %s", [created["id"]])
    assert deleted_at is not None
    assert audit("contact.delete") == [{"label": "Gone Soon", "changes": {}}]
    assert call("delete", one(created["id"]), owner, org).status_code == 404
    assert (
        call(
            "patch",
            one(created["id"]),
            owner,
            org,
            {"updated_at": created["updated_at"], "title": "Z"},
        ).status_code
        == 404
    )
    assert other["name"] == "Keeper"


@pytest.mark.parametrize("role", [Role.ADMIN, Role.MANAGER, Role.MEMBER])
def test_every_role_can_work_with_contacts_it_can_see(tenancy, org, role):
    person = tenancy.member(role, org)
    created = make(person, org, f"{role.name.title()}")
    assert (
        call(
            "patch",
            one(created["id"]),
            person,
            org,
            {"updated_at": created["updated_at"], "title": "Hi"},
        ).status_code
        == 200
    )
    assert call("delete", one(created["id"]), person, org).status_code == 204


def test_no_token_is_401(org):
    assert APIClient().get(LIST).status_code == 401
    assert (
        APIClient().post(LIST, {"first_name": "A", "email": "a@b.com"}, format="json").status_code
        == 401
    )


# ---- tenant isolation: every endpoint


def test_another_organization_cannot_see_or_touch_a_contact(tenancy, org, owner):
    other = tenancy.organization("Other")
    stranger = tenancy.member(Role.OWNER, other)
    mine = make(owner, org, "Secret", email="secret@example.com")
    make(stranger, other, "Theirs")
    assert names(call("get", LIST, stranger, other)) == ["Theirs"]
    assert call("get", LIST, stranger, other).json()["count"] == 1
    assert names(call("get", LIST + "?q=secret", stranger, other)) == []
    assert names(call("get", LIST + f"?owner_id={owner.user_id}", stranger, other)) == []
    assert call("get", one(mine["id"]), stranger, other).status_code == 404
    assert (
        call(
            "patch",
            one(mine["id"]),
            stranger,
            other,
            {"updated_at": mine["updated_at"], "title": "Taken"},
        ).status_code
        == 404
    )
    assert call("delete", one(mine["id"]), stranger, other).status_code == 404
    assert call("get", one(mine["id"]), owner, org).json() == mine
    for method, url, body in (
        ("get", LIST, None),
        ("post", LIST, {"first_name": "Intruder", "email": "i@x.com"}),
        ("get", one(mine["id"]), None),
        ("patch", one(mine["id"]), {"updated_at": mine["updated_at"], "title": "X"}),
        ("delete", one(mine["id"]), None),
    ):
        response = call(method, url, stranger, org, body)
        assert response.status_code == 404 and response.json()["code"] == "COMMON_NOT_FOUND"
    assert names(call("get", LIST, owner, org)) == ["Secret"]


def test_a_contact_cannot_be_linked_to_another_organizations_company_owner_or_team(
    tenancy, org, owner
):
    other = tenancy.organization("Other")
    stranger = tenancy.member(Role.OWNER, other)
    foreign_company = company(stranger, other, "Foreign")
    foreign_team = team_with(other, stranger)
    created = make(owner, org, "Mine")
    for body in (
        {"company_id": foreign_company["id"]},
        {"owner_id": str(stranger.user_id)},
        {"visibility": "team", "team_id": str(foreign_team)},
    ):
        assert (
            call(
                "post", LIST, owner, org, {"first_name": "New", "email": "n@x.com", **body}
            ).status_code
            == 400
        )
        patched = call(
            "patch", one(created["id"]), owner, org, {"updated_at": created["updated_at"], **body}
        )
        assert patched.status_code == 400
    assert call("get", one(created["id"]), owner, org).json() == created


def test_filtering_by_another_organizations_company_returns_nothing(tenancy, org, owner):
    other = tenancy.organization("Other")
    stranger = tenancy.member(Role.OWNER, other)
    foreign_company = company(stranger, other, "Foreign")
    make(stranger, other, "Theirs", company_id=foreign_company["id"])
    make(owner, org, "Mine")
    response = call("get", LIST + f"?company_id={foreign_company['id']}", owner, org)
    assert response.status_code == 200 and response.json()["results"] == []


def test_an_email_is_unique_per_organization_not_globally(tenancy, org, owner):
    other = tenancy.organization("Other")
    make(owner, org, "A", email="shared@example.com")
    make(tenancy.member(Role.OWNER, other), other, "B", email="shared@example.com")
    response = call("post", LIST, owner, org, {"first_name": "C", "email": "shared@example.com"})
    assert response.status_code == 409 and "existing" in response.json()
