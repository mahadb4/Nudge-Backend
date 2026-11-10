"""Company endpoints over HTTP on nudge_test: rules, visibility, optimistic concurrency, audit,
query counts and tenant isolation for every endpoint."""

import json
from uuid import UUID

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from apps.crm.repositories.company_repository import PostgresCompanyRepository
from common.constants import Role
from common.pagination import parse_list_query
from common.tenancy import TenantContext
from config import container

pytestmark = pytest.mark.django_db

LIST = "/api/v1/companies/"


def one(company_id) -> str:
    return f"/api/v1/companies/{company_id}/"


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


def make(who, org_id, name="Acme Corp", **extra) -> dict:
    response = call("post", LIST, who, org_id, {"name": name, **extra})
    assert response.status_code == 201, response.json()
    return response.json()


def names(response) -> list[str]:
    return [c["name"] for c in response.json()["results"]]


def audit(action: str) -> list[dict]:
    rows = sql("SELECT details FROM audit_logs WHERE action = %s ORDER BY created_at", [action])
    return [json.loads(r[0]) if isinstance(r[0], str) else r[0] for r in rows]


def team_with(org_id, *people, name: str = "Sales") -> UUID:
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
    created = make(
        owner, org, "  Acme   Corp ", domain="ACME.com", industry=" Software ", size_range="11-50"
    )
    assert created["name"] == "Acme Corp" and created["domain"] == "acme.com"
    assert created["industry"] == "Software" and created["size_range"] == "11-50"
    assert created["owner"] == {"id": str(owner.user_id), "name": "Person Tester"}
    assert created["visibility"] == "organization" and created["team_id"] is None
    assert (created["people_count"], created["open_deal_count"], created["open_value"]) == (
        0,
        0,
        [],
    )
    assert set(created) == {
        "id",
        "name",
        "domain",
        "industry",
        "size_range",
        "owner",
        "visibility",
        "team_id",
        "people_count",
        "open_deal_count",
        "open_value",
        "created_at",
        "updated_at",
    }


def test_create_is_audited_with_the_label(org, owner):
    created = make(owner, org, "Audited Co")
    assert audit("company.create") == [{"label": "Audited Co", "changes": {}}]
    ((object_id,),) = sql("SELECT object_id FROM audit_logs WHERE action = 'company.create'")
    assert str(object_id) == created["id"]


@pytest.mark.parametrize(
    "body, field, code",
    [
        ({}, "name", "VALIDATION_REQUIRED"),
        ({"name": None}, "name", "VALIDATION_REQUIRED"),
        ({"name": "A"}, "name", "VALIDATION_TOO_SHORT"),
        ({"name": "x" * 121}, "name", "VALIDATION_TOO_LONG"),
        ({"name": "<b>x</b>"}, "name", "VALIDATION_MARKUP_NOT_ALLOWED"),
        (
            {"name": "Ok Co", "domain": "https://acme.com/path"},
            "domain",
            "VALIDATION_DOMAIN_INVALID",
        ),
        ({"name": "Ok Co", "domain": "acme"}, "domain", "VALIDATION_DOMAIN_INVALID"),
        ({"name": "Ok Co", "domain": "a b.com"}, "domain", "VALIDATION_DOMAIN_INVALID"),
        ({"name": "Ok Co", "domain": "-a.com"}, "domain", "VALIDATION_DOMAIN_INVALID"),
        ({"name": "Ok Co", "domain": 5}, "domain", "VALIDATION_INVALID_TYPE"),
        ({"name": "Ok Co", "industry": "x" * 81}, "industry", "VALIDATION_TOO_LONG"),
        ({"name": "Ok Co", "size_range": "huge"}, "size_range", "VALIDATION_CHOICE_INVALID"),
        ({"name": "Ok Co", "visibility": "Private"}, "visibility", "VALIDATION_CHOICE_INVALID"),
        ({"name": "Ok Co", "visibility": None}, "visibility", "VALIDATION_REQUIRED"),
        ({"name": "Ok Co", "owner_id": "nope"}, "owner_id", "VALIDATION_UUID_INVALID"),
        ({"name": "Ok Co", "owner_id": None}, "owner_id", "VALIDATION_REQUIRED"),
        ({"name": "Ok Co", "team_id": "nope"}, "team_id", "VALIDATION_UUID_INVALID"),
    ],
)
def test_create_field_rules(org, owner, body, field, code):
    response = call("post", LIST, owner, org, body)
    assert response.status_code == 400
    assert response.json()["fields"][field][0]["code"] == code
    assert names(call("get", LIST, owner, org)) == []


@pytest.mark.parametrize("field", ["id", "organization_id", "created_at", "deleted_at", "version"])
def test_the_client_cannot_set_server_fields(org, owner, field):
    response = call("post", LIST, owner, org, {"name": "Ok Co", field: "x"})
    assert response.status_code == 400 and field in response.json()["fields"]


def test_duplicate_names_are_409_ignoring_case_and_spaces(org, owner):
    make(owner, org, "Acme Corp")
    for name in ("acme corp", "  ACME   corp "):
        response = call("post", LIST, owner, org, {"name": name})
        assert response.status_code == 409 and response.json()["code"] == "CRM_COMPANY_NAME_TAKEN"


def test_duplicate_domains_are_409_but_empty_domains_are_fine(org, owner):
    make(owner, org, "One", domain="acme.com")
    response = call("post", LIST, owner, org, {"name": "Two", "domain": "ACME.com"})
    assert response.status_code == 409 and response.json()["code"] == "CRM_COMPANY_DOMAIN_TAKEN"
    make(owner, org, "Three")
    make(owner, org, "Four", domain=None)


def test_the_same_name_and_domain_are_fine_in_another_organization(tenancy, org, owner):
    other = tenancy.organization("Other")
    stranger = tenancy.member(Role.OWNER, other)
    make(owner, org, "Acme Corp", domain="acme.com")
    make(stranger, other, "Acme Corp", domain="acme.com")


def test_the_owner_must_be_an_active_member_of_this_organization(tenancy, org, owner, member):
    assert make(owner, org, "Given Away", owner_id=str(member.user_id))["owner"]["id"] == str(
        member.user_id
    )
    other = tenancy.organization("Other")
    foreign = tenancy.member(Role.OWNER, other)
    for who in (foreign.user_id, "00000000-0000-0000-0000-000000000000"):
        response = call("post", LIST, owner, org, {"name": "Bad Owner", "owner_id": str(who)})
        assert response.status_code == 400
        assert response.json()["fields"]["owner_id"][0]["code"] == "VALIDATION_MEMBER_INVALID"
    sql("UPDATE memberships SET status = 3 WHERE user_id = %s", [member.user_id])
    response = call("post", LIST, owner, org, {"name": "Removed", "owner_id": str(member.user_id)})
    assert response.status_code == 400


def test_team_visibility_rules(tenancy, org, owner, member):
    team = team_with(org, member)
    outsider = tenancy.member(Role.MEMBER, org)
    other_org_team = team_with(tenancy.organization("Other"))
    assert make(member, org, "Team Co", visibility="team", team_id=str(team))["team_id"] == str(
        team
    )
    cases = [
        (member, {"visibility": "team"}, "team_id", "VALIDATION_TEAM_REQUIRED"),
        (
            member,
            {"visibility": "organization", "team_id": str(team)},
            "team_id",
            "VALIDATION_TEAM_NOT_ALLOWED",
        ),
        (
            member,
            {"visibility": "private", "team_id": str(team)},
            "team_id",
            "VALIDATION_TEAM_NOT_ALLOWED",
        ),
        (
            outsider,
            {"visibility": "team", "team_id": str(team)},
            "team_id",
            "VALIDATION_TEAM_INVALID",
        ),
        (
            member,
            {"visibility": "team", "team_id": str(other_org_team)},
            "team_id",
            "VALIDATION_TEAM_INVALID",
        ),
        (
            owner,
            {"visibility": "team", "team_id": str(other_org_team)},
            "team_id",
            "VALIDATION_TEAM_INVALID",
        ),
    ]
    for who, extra, field, code in cases:
        response = call("post", LIST, who, org, {"name": "Rejected", **extra})
        assert response.status_code == 400, extra
        assert response.json()["fields"][field][0]["code"] == code
    # An Owner or Admin may use any team of the organization.
    assert make(owner, org, "Admin Team Co", visibility="team", team_id=str(team))


# ---- read: visibility


def test_visibility_decides_who_sees_a_company(tenancy, org, owner, member):
    team = team_with(org, member)
    mate = tenancy.member(Role.MEMBER, org)
    outsider = tenancy.member(Role.MANAGER, org)
    team_with(org, mate, name="Support")  # a second team that has nobody from the first
    make(owner, org, "Public Co")
    private = make(owner, org, "Private Co", visibility="private")
    teamed = make(owner, org, "Team Co", visibility="team", team_id=str(team))
    mine = make(member, org, "Member Private", visibility="private")
    expectations = {
        "owner": (owner, ["Member Private", "Private Co", "Public Co", "Team Co"]),
        "member": (member, ["Member Private", "Public Co", "Team Co"]),
        "outsider": (outsider, ["Public Co"]),
        "mate": (mate, ["Public Co"]),
    }
    for who, expected in expectations.values():
        assert names(call("get", LIST, who, org)) == expected
        assert call("get", LIST, who, org).json()["count"] == len(expected)
    assert call("get", one(private["id"]), outsider, org).status_code == 404
    assert call("get", one(teamed["id"]), outsider, org).status_code == 404
    assert call("get", one(teamed["id"]), member, org).status_code == 200
    assert call("get", one(mine["id"]), owner, org).status_code == 200
    # What you cannot see you cannot change either.
    for method, body in (
        ("patch", {"updated_at": private["updated_at"], "name": "Hijack"}),
        ("delete", None),
    ):
        assert call(method, one(private["id"]), outsider, org, body).status_code == 404
    assert call("get", one(private["id"]), owner, org).json()["name"] == "Private Co"


def test_an_owner_can_assign_a_private_company_to_a_colleague_and_still_get_the_reply(
    org, owner, member
):
    created = make(owner, org, "Handed Over", visibility="private", owner_id=str(member.user_id))
    assert created["owner"]["id"] == str(member.user_id)
    assert call("get", one(created["id"]), owner, org).status_code == 200


# ---- list: pagination, search, ordering, filters


def test_default_order_is_by_name_ignoring_case_and_pages_have_links(org, owner):
    for name in ("beta", "Alpha", "gamma", "Delta", "epsilon"):
        make(owner, org, name)
    first = call("get", LIST + "?page_size=2", owner, org).json()
    assert [c["name"] for c in first["results"]] == ["Alpha", "beta"] and first["count"] == 5
    assert (
        first["previous"] is None and "page=2" in first["next"] and "page_size=2" in first["next"]
    )
    second = call("get", LIST + "?page_size=2&page=2", owner, org).json()
    assert [c["name"] for c in second["results"]] == ["Delta", "epsilon"]
    assert "page=1" in second["previous"] and "page=3" in second["next"]
    last = call("get", LIST + "?page_size=2&page=3", owner, org).json()
    assert [c["name"] for c in last["results"]] == ["gamma"] and last["next"] is None
    beyond = call("get", LIST + "?page_size=2&page=9", owner, org).json()
    assert beyond["results"] == [] and beyond["count"] == 5


def test_ordering_by_newest_first(org, owner):
    ids = [make(owner, org, name)["id"] for name in ("First", "Second", "Third")]
    for age, company_id in enumerate(ids):
        sql(
            "UPDATE companies SET created_at = now() + make_interval(secs => %s) WHERE id = %s",
            [age, company_id],
        )
    assert names(call("get", LIST + "?ordering=-created_at", owner, org)) == [
        "Third",
        "Second",
        "First",
    ]
    assert names(call("get", LIST + "?ordering=name", owner, org)) == ["First", "Second", "Third"]


def test_search_covers_name_domain_and_industry_and_treats_wildcards_literally(org, owner):
    make(owner, org, "Northwind Traders", domain="northwind.io", industry="Retail")
    make(owner, org, "Contoso", domain="contoso.com", industry="Software")
    make(owner, org, "100% Real", industry="Odd_Industry")
    make(owner, org, "Dxi Co")
    assert names(call("get", LIST + "?q=northwind", owner, org)) == ["Northwind Traders"]
    assert names(call("get", LIST + "?q=CONTOSO.com", owner, org)) == ["Contoso"]
    assert names(call("get", LIST + "?q=soft", owner, org)) == ["Contoso"]
    assert names(call("get", LIST + "?q=0%25%20R", owner, org)) == ["100% Real"]
    assert names(call("get", LIST + "?q=d_i", owner, org)) == ["100% Real"]
    assert names(call("get", LIST + "?q=nothing-here", owner, org)) == []
    assert len(names(call("get", LIST + "?q=", owner, org))) == 4


def test_filter_by_owner(org, owner, member):
    make(owner, org, "Mine")
    make(member, org, "Theirs")
    assert names(call("get", LIST + f"?owner_id={member.user_id}", owner, org)) == ["Theirs"]


@pytest.mark.parametrize(
    "query, field, code",
    [
        ("?page=0", "page", "VALIDATION_PAGE_INVALID"),
        ("?page=abc", "page", "VALIDATION_PAGE_INVALID"),
        ("?page=-1", "page", "VALIDATION_PAGE_INVALID"),
        ("?page_size=0", "page_size", "VALIDATION_PAGE_SIZE_INVALID"),
        ("?page_size=101", "page_size", "VALIDATION_PAGE_SIZE_INVALID"),
        ("?ordering=-name", "ordering", "VALIDATION_CHOICE_INVALID"),
        ("?ordering=password", "ordering", "VALIDATION_CHOICE_INVALID"),
        ("?q=a", "q", "VALIDATION_TOO_SHORT"),
        ("?q=" + "x" * 101, "q", "VALIDATION_TOO_LONG"),
        ("?owner_id=nope", "owner_id", "VALIDATION_UUID_INVALID"),
        ("?status=active", "status", "VALIDATION_UNKNOWN_FIELD"),
        ("?organization_id=1", "organization_id", "VALIDATION_UNKNOWN_FIELD"),
    ],
)
def test_bad_query_parameters_name_the_parameter(org, owner, query, field, code):
    response = call("get", LIST + query, owner, org)
    assert response.status_code == 400
    assert response.json()["fields"][field][0]["code"] == code


def test_the_page_size_is_capped_at_100(org, owner):
    assert call("get", LIST + "?page_size=100", owner, org).status_code == 200


def test_parse_list_query_reports_every_problem_together():
    from common.errors import ValidationFailed

    with pytest.raises(ValidationFailed) as info:
        parse_list_query(
            {"page": "0", "q": "a", "zzz": "1"}, orderings=("name",), default_ordering="name"
        )
    assert set(info.value.fields) == {"page", "q", "zzz"}


# ---- list: derived numbers and query counts


def add_contact(org_id, owner_id, company_id, deleted=False):
    sql(
        "INSERT INTO contacts (organization_id, company_id, owner_id, first_name, deleted_at) "
        "VALUES (%s, %s, %s, 'Pat', %s)",
        [org_id, company_id, owner_id, "2026-01-01T00:00:00Z" if deleted else None],
    )


def add_deal(org_id, owner_id, company_id, stage_name, amount, currency="USD", deleted=False):
    sql(
        "INSERT INTO deals (organization_id, company_id, stage_id, owner_id, title, amount, "
        "currency, deleted_at) SELECT %s, %s, id, %s, 'Deal', %s, %s, %s FROM deal_stages "
        "WHERE organization_id = %s AND name = %s",
        [
            org_id,
            company_id,
            owner_id,
            amount,
            currency,
            "2026-01-01T00:00:00Z" if deleted else None,
            org_id,
            stage_name,
        ],
    )


def test_people_and_open_deal_numbers(org, owner):
    company = make(owner, org, "Numbers Co")
    other = make(owner, org, "Quiet Co")
    add_contact(org, owner.user_id, company["id"])
    add_contact(org, owner.user_id, company["id"])
    add_contact(org, owner.user_id, company["id"], deleted=True)
    add_deal(org, owner.user_id, company["id"], "New", "100.50")
    add_deal(org, owner.user_id, company["id"], "Proposal", "200.00")
    add_deal(org, owner.user_id, company["id"], "New", "50", currency="EUR")
    add_deal(org, owner.user_id, company["id"], "Won", "999")  # closed: not open value
    add_deal(org, owner.user_id, company["id"], "Lost", "999")
    add_deal(org, owner.user_id, company["id"], "New", "999", deleted=True)
    results = {c["name"]: c for c in call("get", LIST, owner, org).json()["results"]}
    numbers = results["Numbers Co"]
    assert (numbers["people_count"], numbers["open_deal_count"]) == (2, 3)
    assert numbers["open_value"] == [
        {"currency": "EUR", "amount": "50.00"},
        {"currency": "USD", "amount": "300.50"},
    ]
    assert (results["Quiet Co"]["people_count"], results["Quiet Co"]["open_value"]) == (0, [])
    assert call("get", one(company["id"]), owner, org).json()["open_deal_count"] == 3
    assert other["id"] != company["id"]


def test_the_list_runs_a_fixed_number_of_queries_however_many_companies(tenancy, org, owner):
    repo = PostgresCompanyRepository()
    context = TenantContext(owner.user_id, org, Role.OWNER)
    query = parse_list_query({}, orderings=("name", "-created_at"), default_ordering="name")

    def run() -> int:
        with CaptureQueriesContext(connection) as queries:
            repo.list_page(context, query)
        return len(queries)

    make(owner, org, "Only One")
    with_one = run()
    for index in range(20):
        company = make(owner, org, f"Company {index:02d}", owner_id=str(owner.user_id))
        add_contact(org, owner.user_id, company["id"])
        add_deal(org, owner.user_id, company["id"], "New", "10", currency="USD")
        add_deal(org, owner.user_id, company["id"], "New", "10", currency="EUR")
    with_many = run()
    assert with_one == with_many <= 5


def test_the_list_endpoint_query_count_does_not_grow_with_the_page(org, owner):
    def api_queries() -> int:
        with CaptureQueriesContext(connection) as queries:
            assert call("get", LIST, owner, org).status_code == 200
        return len(queries)

    make(owner, org, "Seed")
    small = api_queries()
    for index in range(15):
        make(owner, org, f"More {index:02d}")
    assert api_queries() == small


# ---- get


def test_get_one_returns_the_same_shape(org, owner):
    created = make(owner, org, "Get Me")
    assert call("get", one(created["id"]), owner, org).json() == created


def test_get_unknown_or_malformed_id(org, owner):
    assert call("get", one("00000000-0000-0000-0000-000000000000"), owner, org).status_code == 404
    assert call("get", LIST + "not-a-uuid/", owner, org).status_code == 404


# ---- update


def test_update_changes_only_what_was_sent_and_moves_updated_at(org, owner):
    created = make(owner, org, "Old Name", domain="old.com", industry="Retail", size_range="1-10")
    response = call(
        "patch",
        one(created["id"]),
        owner,
        org,
        {"updated_at": created["updated_at"], "name": "New Name"},
    )
    body = response.json()
    assert response.status_code == 200 and body["name"] == "New Name"
    assert (body["domain"], body["industry"], body["size_range"]) == ("old.com", "Retail", "1-10")
    assert (
        body["updated_at"] > created["updated_at"] and body["created_at"] == created["created_at"]
    )
    assert audit("company.update") == [
        {"label": "Old Name", "changes": {"name": {"from": "Old Name", "to": "New Name"}}}
    ]


def test_update_can_clear_optional_fields_with_null(org, owner):
    created = make(
        owner, org, "Clear Me", domain="clear.com", industry="Retail", size_range="51-200"
    )
    body = call(
        "patch",
        one(created["id"]),
        owner,
        org,
        {"updated_at": created["updated_at"], "domain": None, "industry": None, "size_range": None},
    ).json()
    assert (body["domain"], body["industry"], body["size_range"]) == (None, None, None)


def test_update_requires_updated_at(org, owner):
    created = make(owner, org, "No Stamp")
    for body in (
        {"name": "X Y"},
        {"name": "X Y", "updated_at": None},
        {"name": "X Y", "updated_at": "yesterday"},
        {"name": "X Y", "updated_at": "2026-01-01T00:00:00"},
    ):
        response = call("patch", one(created["id"]), owner, org, body)
        assert response.status_code == 400 and "updated_at" in response.json()["fields"]


def test_a_stale_updated_at_is_409_with_the_current_company(org, owner):
    created = make(owner, org, "Race Co")
    first = call(
        "patch",
        one(created["id"]),
        owner,
        org,
        {"updated_at": created["updated_at"], "name": "Race Won"},
    )
    assert first.status_code == 200
    stale = call(
        "patch",
        one(created["id"]),
        owner,
        org,
        {"updated_at": created["updated_at"], "name": "Race Lost"},
    )
    assert stale.status_code == 409 and stale.json()["code"] == "COMMON_VERSION_CONFLICT"
    assert stale.json()["current"]["name"] == "Race Won"
    assert call("get", one(created["id"]), owner, org).json()["name"] == "Race Won"
    fresh = call(
        "patch",
        one(created["id"]),
        owner,
        org,
        {"updated_at": first.json()["updated_at"], "name": "Race Third"},
    )
    assert fresh.status_code == 200


def test_an_update_that_changes_nothing_writes_nothing(org, owner):
    created = make(owner, org, "Same Co", domain="same.com")
    response = call(
        "patch",
        one(created["id"]),
        owner,
        org,
        {"updated_at": created["updated_at"], "name": "Same Co", "domain": "SAME.com"},
    )
    assert response.status_code == 200 and response.json()["updated_at"] == created["updated_at"]
    assert audit("company.update") == []


def test_renaming_rules(org, owner):
    first, second = make(owner, org, "First Co"), make(owner, org, "Second Co")
    clash = call(
        "patch",
        one(second["id"]),
        owner,
        org,
        {"updated_at": second["updated_at"], "name": "first co"},
    )
    assert clash.status_code == 409 and clash.json()["code"] == "CRM_COMPANY_NAME_TAKEN"
    case_only = call(
        "patch",
        one(first["id"]),
        owner,
        org,
        {"updated_at": first["updated_at"], "name": "FIRST CO"},
    )
    assert case_only.status_code == 200 and case_only.json()["name"] == "FIRST CO"


def test_changing_to_a_taken_domain_is_409(org, owner):
    make(owner, org, "Has Domain", domain="taken.com")
    other = make(owner, org, "Wants Domain")
    response = call(
        "patch",
        one(other["id"]),
        owner,
        org,
        {"updated_at": other["updated_at"], "domain": "taken.com"},
    )
    assert response.status_code == 409 and response.json()["code"] == "CRM_COMPANY_DOMAIN_TAKEN"


def test_update_checks_owner_and_team_like_create(tenancy, org, owner, member):
    team = team_with(org, member)
    created = make(member, org, "Linked Co")
    stamp = created["updated_at"]
    bad_owner = call(
        "patch",
        one(created["id"]),
        member,
        org,
        {"updated_at": stamp, "owner_id": str(tenancy.person().user_id)},
    )
    assert bad_owner.status_code == 400 and "owner_id" in bad_owner.json()["fields"]
    no_team = call(
        "patch", one(created["id"]), member, org, {"updated_at": stamp, "visibility": "team"}
    )
    assert no_team.json()["fields"]["team_id"][0]["code"] == "VALIDATION_TEAM_REQUIRED"
    teamed = call(
        "patch",
        one(created["id"]),
        member,
        org,
        {"updated_at": stamp, "visibility": "team", "team_id": str(team)},
    )
    assert teamed.status_code == 200 and teamed.json()["team_id"] == str(team)
    back = call(
        "patch",
        one(created["id"]),
        member,
        org,
        {"updated_at": teamed.json()["updated_at"], "visibility": "private"},
    )
    assert back.status_code == 200 and back.json()["team_id"] is None


def test_update_unknown_fields_are_refused(org, owner):
    created = make(owner, org, "Strict Co")
    response = call(
        "patch",
        one(created["id"]),
        owner,
        org,
        {"updated_at": created["updated_at"], "organization_id": "x"},
    )
    assert response.status_code == 400 and "organization_id" in response.json()["fields"]


# ---- delete


def test_delete_is_soft_audited_and_frees_the_name(org, owner):
    created = make(owner, org, "Gone Co", domain="gone.com")
    other = make(owner, org, "Keeper")
    response = call("delete", one(created["id"]), owner, org)
    assert response.status_code == 204 and response.content == b""
    assert call("get", one(created["id"]), owner, org).status_code == 404
    assert names(call("get", LIST, owner, org)) == ["Keeper"]
    ((deleted_at,),) = sql("SELECT deleted_at FROM companies WHERE id = %s", [created["id"]])
    assert deleted_at is not None
    assert audit("company.delete") == [{"label": "Gone Co", "changes": {}}]
    assert call("delete", one(created["id"]), owner, org).status_code == 404
    assert (
        call(
            "patch",
            one(created["id"]),
            owner,
            org,
            {"updated_at": created["updated_at"], "name": "Zombie"},
        ).status_code
        == 404
    )
    again = make(owner, org, "Gone Co", domain="gone.com")
    assert again["id"] != created["id"] and other["name"] == "Keeper"


def test_deleting_a_company_keeps_its_people_and_deals(org, owner):
    company = make(owner, org, "Has People")
    add_contact(org, owner.user_id, company["id"])
    call("delete", one(company["id"]), owner, org)
    assert sql("SELECT count(*) FROM contacts WHERE company_id = %s", [company["id"]]) == [(1,)]


# ---- members of any role can work; auth is required


@pytest.mark.parametrize("role", [Role.ADMIN, Role.MANAGER, Role.MEMBER])
def test_every_role_can_create_update_and_delete_visible_companies(tenancy, org, role):
    person = tenancy.member(role, org)
    created = make(person, org, f"{role.name} Co")
    changed = call(
        "patch",
        one(created["id"]),
        person,
        org,
        {"updated_at": created["updated_at"], "industry": "Retail"},
    )
    assert changed.status_code == 200
    assert call("delete", one(created["id"]), person, org).status_code == 204


def test_no_token_is_401(org):
    client = APIClient()
    assert client.get(LIST).status_code == 401
    assert client.post(LIST, {"name": "No Token"}, format="json").status_code == 401


# ---- tenant isolation: every endpoint


def test_another_organization_cannot_see_or_touch_a_company(tenancy, org, owner):
    other = tenancy.organization("Other")
    stranger = tenancy.member(Role.OWNER, other)
    mine = make(owner, org, "Secret Co", domain="secret.com")
    theirs = make(stranger, other, "Their Co")
    # list
    assert names(call("get", LIST, stranger, other)) == ["Their Co"]
    assert call("get", LIST, stranger, other).json()["count"] == 1
    assert names(call("get", LIST + "?q=secret", stranger, other)) == []
    assert names(call("get", LIST + f"?owner_id={owner.user_id}", stranger, other)) == []
    # get / patch / delete with a foreign id: 404, nothing changes
    assert call("get", one(mine["id"]), stranger, other).status_code == 404
    patched = call(
        "patch",
        one(mine["id"]),
        stranger,
        other,
        {"updated_at": mine["updated_at"], "name": "Taken"},
    )
    assert patched.status_code == 404
    assert call("delete", one(mine["id"]), stranger, other).status_code == 404
    assert call("get", one(mine["id"]), owner, org).json() == mine
    # naming the other organization in the header without belonging to it: 404 on every endpoint
    for method, url, body in (
        ("get", LIST, None),
        ("post", LIST, {"name": "Intruder"}),
        ("get", one(mine["id"]), None),
        ("patch", one(mine["id"]), {"updated_at": mine["updated_at"], "name": "X Y"}),
        ("delete", one(mine["id"]), None),
    ):
        response = call(method, url, stranger, org, body)
        assert response.status_code == 404 and response.json()["code"] == "COMMON_NOT_FOUND"
    assert names(call("get", LIST, owner, org)) == ["Secret Co"]
    assert theirs["name"] == "Their Co"


def test_a_company_cannot_be_given_to_a_user_or_team_of_another_organization(tenancy, org, owner):
    other = tenancy.organization("Other")
    stranger = tenancy.member(Role.OWNER, other)
    foreign_team = team_with(other, stranger)
    created = make(owner, org, "Mine")
    for body in (
        {"owner_id": str(stranger.user_id)},
        {"visibility": "team", "team_id": str(foreign_team)},
    ):
        assert call("post", LIST, owner, org, {"name": "New One", **body}).status_code == 400
        patched = call(
            "patch", one(created["id"]), owner, org, {"updated_at": created["updated_at"], **body}
        )
        assert patched.status_code == 400
    assert call("get", one(created["id"]), owner, org).json() == created


def test_a_company_created_in_one_organization_never_appears_in_another(tenancy, org, owner):
    other = tenancy.organization("Other")
    stranger = tenancy.member(Role.OWNER, other)
    make(owner, org, "Only Here")
    assert names(call("get", LIST, stranger, other)) == []
    assert sql("SELECT count(DISTINCT organization_id) FROM companies") == [(1,)]


def test_the_container_builds_the_company_service(org):
    assert container.company_service() is not None
