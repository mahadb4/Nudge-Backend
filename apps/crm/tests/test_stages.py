"""Default stages and the stage repository on the real test database, including tenant
isolation."""

import pytest
from django.db import connection
from django.db import transaction as db_transaction

from apps.crm.domain.defaults import DEFAULT_STAGES
from apps.crm.domain.enums import StageOutcome
from apps.crm.domain.errors import DuplicateStageName
from apps.crm.repositories.stage_repository import PostgresStageRepository
from common.constants import Role
from common.tenancy import TenantContext
from config import container

pytestmark = pytest.mark.django_db


def ctx(organization_id, role=Role.OWNER) -> TenantContext:
    return TenantContext(container.ids().new_id(), organization_id, role)


@pytest.fixture
def repo() -> PostgresStageRepository:
    return PostgresStageRepository()


@pytest.fixture
def service():
    return container.stage_service()


def test_seed_creates_the_seven_default_stages_in_order(tenancy, service):
    context = ctx(tenancy.organization(seed_stages=False))
    stages = service.seed_defaults(context)
    assert [(s.name, s.position, s.outcome) for s in stages] == [
        ("New", 0, StageOutcome.OPEN),
        ("Contacted", 1, StageOutcome.OPEN),
        ("Meeting scheduled", 2, StageOutcome.OPEN),
        ("Proposal", 3, StageOutcome.OPEN),
        ("Negotiation", 4, StageOutcome.OPEN),
        ("Won", 5, StageOutcome.WON),
        ("Lost", 6, StageOutcome.LOST),
    ]
    assert all(s.organization_id == context.organization_id for s in stages)


def test_seeding_twice_changes_nothing(tenancy, service, repo):
    context = ctx(tenancy.organization(seed_stages=False))
    first = service.seed_defaults(context)
    assert service.seed_defaults(context) == first
    assert repo.count(context) == 7


def test_our_defaults_match_the_database_function(tenancy, service, repo):
    ours = ctx(tenancy.organization("Ours", seed_stages=False))
    sql = ctx(tenancy.organization("SQL", seed_stages=False))
    service.seed_defaults(ours)
    with connection.cursor() as cursor:
        cursor.execute("SELECT nudge_create_default_stages(%s)", [sql.organization_id])

    def as_tuples(context):
        return [(s.name, s.position, s.outcome) for s in repo.list_all(context)]

    assert as_tuples(ours) == as_tuples(sql)
    assert [(n, o) for n, o in DEFAULT_STAGES] == [(n, o) for n, _, o in as_tuples(ours)]


# ---- tenant isolation: every method, with another organization's context


def insert_deal(context, stage_id, owner_id, deleted_at=None) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO deals (organization_id, stage_id, owner_id, title, amount, currency, "
            "deleted_at) VALUES (%s, %s, %s, 'Deal', 100, 'USD', %s)",
            [context.organization_id, stage_id, owner_id, deleted_at],
        )


def test_one_organization_never_sees_or_changes_anothers_stages(tenancy, repo):
    a, b = ctx(tenancy.organization("A")), ctx(tenancy.organization("B"))
    a_stages = repo.list_all(a)
    target = a_stages[1]
    assert {s.organization_id for s in repo.list_all(b)} == {b.organization_id}
    assert {s.id for s in repo.list_all(a)}.isdisjoint({s.id for s in repo.list_all(b)})
    assert target.id not in {s.id for s in repo.lock_all(b)}
    repo.rename(b, target.id, "Hijacked")
    repo.set_positions(b, [target.id])
    assert repo.delete(b, target.id) is False
    assert repo.count_deals(b, target.id) == 0
    assert repo.list_all(a) == a_stages
    assert repo.delete(a, target.id) is True


def test_the_same_name_in_one_organization_is_refused_ignoring_case(tenancy, repo):
    context = ctx(tenancy.organization())
    with pytest.raises(DuplicateStageName), db_transaction.atomic():
        repo.create(
            context,
            stage_id=container.ids().new_id(),
            name="NEW",
            position=9,
            outcome=StageOutcome.OPEN,
        )
    target = repo.list_all(context)[1]
    with pytest.raises(DuplicateStageName), db_transaction.atomic():
        repo.rename(context, target.id, "new")


def test_two_organizations_may_use_the_same_stage_names(tenancy, repo):
    a, b = ctx(tenancy.organization("A")), ctx(tenancy.organization("B"))
    assert [s.name for s in repo.list_all(a)] == [s.name for s in repo.list_all(b)]


def test_set_positions_rewrites_zero_to_n_minus_one(tenancy, repo):
    context = ctx(tenancy.organization())
    ids = [s.id for s in repo.list_all(context)]
    repo.set_positions(context, [ids[0], ids[2], ids[1], *ids[3:]])
    after = repo.list_all(context)
    assert [s.position for s in after] == list(range(7))
    assert [s.id for s in after][:3] == [ids[0], ids[2], ids[1]]


def test_list_with_counts_uses_two_queries_and_counts_live_deals_only(
    tenancy, repo, django_assert_num_queries
):
    context = ctx(tenancy.organization())
    stage = repo.list_all(context)[0]
    owner = tenancy.person()
    tenancy.join(owner, context.organization_id, Role.OWNER)
    for deleted_at in (None, None, "2026-01-01T00:00:00Z"):
        insert_deal(context, stage.id, owner.user_id, deleted_at)
    with django_assert_num_queries(2):
        summaries = repo.list_with_counts(context)
    assert summaries[0].deal_count == 2 and all(s.deal_count == 0 for s in summaries[1:])
    assert repo.count_deals(context, stage.id) == 3  # the soft-deleted one still blocks a delete
