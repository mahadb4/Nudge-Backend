"""Default stages: repository on the real database, service with the real repository."""

from uuid import UUID

import pytest
from django.db import IntegrityError, connection

from apps.accounts.repositories.organization_repository import PostgresOrganizationRepository
from apps.crm.domain.defaults import DEFAULT_STAGES
from apps.crm.domain.enums import StageOutcome
from apps.crm.repositories.stage_repository import PostgresStageRepository
from apps.crm.services.stage_service import StageService
from common.constants import AccountType
from common.infra.clock import SystemClock
from common.infra.ids import UuidV7Generator

pytestmark = pytest.mark.django_db

IDS = UuidV7Generator(SystemClock())


def new_organization(name: str = "Acme") -> UUID:
    return (
        PostgresOrganizationRepository()
        .create(
            organization_id=IDS.new_id(),
            name=name,
            account_type=AccountType.BUSINESS,
            timezone="UTC",
        )
        .id
    )


@pytest.fixture
def service() -> StageService:
    return StageService(PostgresStageRepository(), IDS)


def test_seed_creates_the_seven_default_stages_in_order(service):
    org = new_organization()
    stages = service.seed_defaults(org)
    assert [(s.name, s.position, s.outcome) for s in stages] == [
        ("New", 0, StageOutcome.OPEN),
        ("Contacted", 1, StageOutcome.OPEN),
        ("Meeting scheduled", 2, StageOutcome.OPEN),
        ("Proposal", 3, StageOutcome.OPEN),
        ("Negotiation", 4, StageOutcome.OPEN),
        ("Won", 5, StageOutcome.WON),
        ("Lost", 6, StageOutcome.LOST),
    ]
    assert all(s.organization_id == org for s in stages)


def test_seeding_twice_changes_nothing(service):
    org = new_organization()
    first = service.seed_defaults(org)
    assert service.seed_defaults(org) == first
    assert PostgresStageRepository().count(org) == 7


def test_our_defaults_match_the_database_function(service):
    """Parity with nudge_create_default_stages() from the seed SQL: same names, positions and
    outcomes."""
    ours_org, sql_org = new_organization("Ours"), new_organization("SQL")
    service.seed_defaults(ours_org)
    with connection.cursor() as cursor:
        cursor.execute("SELECT nudge_create_default_stages(%s)", [sql_org])
    repository = PostgresStageRepository()

    def as_tuples(org):
        return [(s.name, s.position, s.outcome) for s in repository.list_for_organization(org)]

    assert as_tuples(ours_org) == as_tuples(sql_org)
    assert [(name, outcome) for name, outcome in DEFAULT_STAGES] == [
        (n, o) for n, _, o in as_tuples(ours_org)
    ]


def test_stages_are_listed_per_organization(service):
    a, b = new_organization("A"), new_organization("B")
    service.seed_defaults(a)
    assert PostgresStageRepository().list_for_organization(b) == []  # tenant isolation
    assert len(PostgresStageRepository().list_for_organization(a)) == 7


def test_the_same_name_in_one_organization_is_refused_ignoring_case(service):
    org = new_organization()
    service.seed_defaults(org)
    with pytest.raises(IntegrityError):
        PostgresStageRepository().create(
            stage_id=IDS.new_id(),
            organization_id=org,
            name="NEW",
            position=9,
            outcome=StageOutcome.OPEN,
        )


def test_two_organizations_may_use_the_same_stage_names(service):
    service.seed_defaults(new_organization("A"))
    service.seed_defaults(new_organization("B"))
