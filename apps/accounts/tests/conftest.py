"""Fixtures for the accounts repository tests (real database, nudge_test)."""

from datetime import UTC, datetime
from uuid import UUID

import pytest
from django.core.cache import caches
from rest_framework.test import APIClient

from apps.accounts.domain.entities import Organization, User
from apps.accounts.repositories.membership_repository import PostgresMembershipRepository
from apps.accounts.repositories.organization_repository import PostgresOrganizationRepository
from apps.accounts.repositories.session_repository import PostgresSessionRepository
from apps.accounts.repositories.user_repository import PostgresUserRepository
from common.constants import AccountType, Role
from common.infra.clock import FrozenClock, SystemClock
from common.infra.ids import UuidV7Generator
from common.tests.fakes import FakePasswordHasher
from config import container

# The database compares expires_at with its own now(), so the base time must be the real time (whole
# seconds).
NOW = datetime.now(UTC).replace(microsecond=0)


@pytest.fixture
def ids() -> UuidV7Generator:
    return UuidV7Generator(SystemClock())


@pytest.fixture
def users() -> PostgresUserRepository:
    return PostgresUserRepository()


@pytest.fixture
def organizations() -> PostgresOrganizationRepository:
    return PostgresOrganizationRepository()


@pytest.fixture
def memberships() -> PostgresMembershipRepository:
    return PostgresMembershipRepository()


@pytest.fixture
def sessions() -> PostgresSessionRepository:
    return PostgresSessionRepository()


@pytest.fixture
def make_user(users, ids):
    def make(email: str = "ali@example.com", full_name: str = "Ali Raza") -> User:
        return users.create(
            user_id=ids.new_id(),
            email=email,
            password_hash="argon2$fake",
            full_name=full_name,
            timezone="Asia/Karachi",
        )

    return make


@pytest.fixture
def make_organization(organizations, ids):
    def make(
        name: str = "Acme Sales", account_type: AccountType = AccountType.BUSINESS
    ) -> Organization:
        return organizations.create(
            organization_id=ids.new_id(),
            name=name,
            account_type=account_type,
            timezone="Asia/Karachi",
        )

    return make


@pytest.fixture
def make_membership(memberships, ids):
    def make(organization_id: UUID, user_id: UUID, role: Role = Role.OWNER):
        return memberships.create(
            membership_id=ids.new_id(), organization_id=organization_id, user_id=user_id, role=role
        )

    return make


@pytest.fixture(autouse=True)
def fast_setup(monkeypatch):
    """Empty cache for every test, and a fast fake password hasher (Argon2 needs 100 MB and ~0.2 s
    per hash)."""
    caches["default"].clear()
    monkeypatch.setattr(container, "password_hasher", lambda: FakePasswordHasher())


@pytest.fixture
def clock(monkeypatch) -> FrozenClock:
    frozen = FrozenClock(datetime.now(UTC))
    monkeypatch.setattr(container, "clock", lambda: frozen)
    return frozen


@pytest.fixture
def client() -> APIClient:
    return APIClient()
