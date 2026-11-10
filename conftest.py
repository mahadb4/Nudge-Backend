"""Project-wide pytest fixtures.

django_db_setup replaces pytest-django's default, which would run migrate. Instead nudge_test is
rebuilt from the SQL files once per session (common/testdb.py). Each test still runs inside a
transaction that is rolled back (pytest-django's db fixture).

`tenancy` builds users, organizations and memberships for API tests of tenant endpoints, with a
real access token for each user.
"""

from dataclasses import dataclass
from uuid import UUID

import pytest
from django.conf import settings
from django.db import connection

from common.constants import AccountType, Role
from common.testdb import build_test_database, parse_target


@pytest.fixture(scope="session")
def django_db_setup(django_db_blocker):
    with django_db_blocker.unblock():
        connection.close()
        build_test_database(
            parse_target(settings.TEST_DATABASE_URL),
            dev_name=settings.DEV_DATABASE_NAME,
            schema_sql=settings.NUDGE_SCHEMA_SQL,
            seed_sql=settings.NUDGE_SEED_SQL,
        )


@pytest.fixture(autouse=True)
def _immediate_constraints(request):
    """Composite tenant FKs are DEFERRABLE INITIALLY DEFERRED and the test transaction never
    commits, so without this a cross-organization link would never fail inside a test."""
    if "db" not in request.fixturenames and request.node.get_closest_marker("django_db") is None:
        return
    request.getfixturevalue("db")
    with connection.cursor() as cursor:
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")


@dataclass(frozen=True)
class Person:
    """A user with a live session. headers() are the HTTP headers of a request they make."""

    user_id: UUID
    token: str

    def headers(self, organization_id: UUID | str | None = None) -> dict[str, str]:
        extra = {"HTTP_X_ORGANIZATION_ID": str(organization_id)} if organization_id else {}
        return {"HTTP_AUTHORIZATION": f"Bearer {self.token}", **extra}


class Tenancy:
    def __init__(self) -> None:
        from config import container

        self._container = container
        self._counter = 0
        self._joined = 0

    def person(self, name: str = "Person") -> Person:
        """A verified user (not yet in any organization) with a session and an access token."""
        from apps.accounts.repositories.user_repository import PostgresUserRepository
        from common.infra.clock import SystemClock

        self._counter += 1
        container = self._container
        now = SystemClock().now()
        user = PostgresUserRepository().create(
            user_id=container.ids().new_id(),
            email=f"person{self._counter}@example.com",
            password_hash="fake$x",
            full_name=f"{name} Tester",
            timezone="UTC",
        )
        PostgresUserRepository().mark_email_verified(user.id, now)
        tokens = container.session_service().start(
            user_id=user.id, remember=False, ip_address=None, device_name=None
        )
        return Person(user.id, tokens.access_token)

    def organization(self, name: str = "Acme", *, seed_stages: bool = True) -> UUID:
        from apps.accounts.repositories.organization_repository import (
            PostgresOrganizationRepository,
        )
        from common.tenancy import TenantContext

        container = self._container
        organization = PostgresOrganizationRepository().create(
            organization_id=container.ids().new_id(),
            name=name,
            account_type=AccountType.BUSINESS,
            timezone="UTC",
        )
        if seed_stages:
            owner = TenantContext(container.ids().new_id(), organization.id, Role.OWNER)
            container.stage_service().seed_defaults(owner)
        return organization.id

    def join(self, person: Person, organization_id: UUID, role: Role) -> None:
        from apps.accounts.repositories.membership_repository import PostgresMembershipRepository

        made = PostgresMembershipRepository().create(
            membership_id=self._container.ids().new_id(),
            organization_id=organization_id,
            user_id=person.user_id,
            role=role,
        )
        # One test transaction gives every row the same now(); make "oldest first" deterministic.
        self._joined += 1
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE memberships SET created_at = now() + make_interval(secs => %s) "
                "WHERE id = %s",
                [self._joined, made.id],
            )

    def member(self, role: Role, organization_id: UUID, name: str = "Person") -> Person:
        person = self.person(name)
        self.join(person, organization_id, role)
        return person


@pytest.fixture
def tenancy(db) -> Tenancy:
    return Tenancy()
