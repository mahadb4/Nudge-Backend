"""audit_logs: insert through the service, and the database refuses to change or delete rows."""

import json
from uuid import UUID

import pytest
from django.db import DatabaseError, IntegrityError, connection, transaction

from apps.accounts.repositories.organization_repository import PostgresOrganizationRepository
from apps.accounts.repositories.user_repository import PostgresUserRepository
from apps.audit.repositories.audit_repository import PostgresAuditRepository
from apps.audit.services.audit_service import AuditService
from common.constants import AccountType, ActorType, AuditAction
from common.infra.clock import SystemClock
from common.infra.ids import UuidV7Generator
from common.interfaces import AuditEvent

pytestmark = pytest.mark.django_db

IDS = UuidV7Generator(SystemClock())


@pytest.fixture
def service() -> AuditService:
    return AuditService(PostgresAuditRepository(), IDS)


@pytest.fixture
def user_id() -> UUID:
    return (
        PostgresUserRepository()
        .create(
            user_id=IDS.new_id(),
            email="ali@example.com",
            password_hash="x",
            full_name="Ali Raza",
            timezone="UTC",
        )
        .id
    )


@pytest.fixture
def organization_id() -> UUID:
    return (
        PostgresOrganizationRepository()
        .create(
            organization_id=IDS.new_id(),
            name="Acme",
            account_type=AccountType.BUSINESS,
            timezone="UTC",
        )
        .id
    )


def rows() -> list[tuple]:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT action, actor_type, actor_id, organization_id, object_type, object_id, "
            "details, host(ip_address) FROM audit_logs"
        )
        # A raw cursor returns jsonb as text, so parse it here.
        return [(*row[:6], json.loads(row[6]), row[7]) for row in cursor.fetchall()]


def test_an_event_is_stored_with_every_field(service, user_id, organization_id):
    service.write(
        AuditEvent(
            action=AuditAction.USER_REGISTER,
            actor_type=ActorType.USER,
            actor_id=user_id,
            organization_id=organization_id,
            object_type="user",
            object_id=user_id,
            details={"account_type": "business"},
            ip_address="203.0.113.9",
        )
    )
    assert rows() == [
        (
            "user.register",
            1,
            user_id,
            organization_id,
            "user",
            user_id,
            {"account_type": "business"},
            "203.0.113.9",
        )
    ]


def test_a_system_event_needs_no_actor_or_organization(service):
    service.write(
        AuditEvent(
            action=AuditAction.USER_LOGIN_FAILED,
            actor_type=ActorType.SYSTEM,
            actor_id=None,
            organization_id=None,
        )
    )
    assert rows() == [("user.login_failed", 2, None, None, None, None, {}, None)]


def test_a_user_event_without_an_actor_is_refused_by_the_database(service):
    with pytest.raises(IntegrityError):
        service.write(
            AuditEvent(
                action=AuditAction.USER_LOGIN,
                actor_type=ActorType.USER,
                actor_id=None,
                organization_id=None,
            )
        )


def test_rows_cannot_be_updated_or_deleted(service):
    service.write(
        AuditEvent(
            action=AuditAction.USER_LOGOUT,
            actor_type=ActorType.SYSTEM,
            actor_id=None,
            organization_id=None,
        )
    )
    for statement in ("UPDATE audit_logs SET action = 'user.login'", "DELETE FROM audit_logs"):
        with (
            pytest.raises(DatabaseError, match="append-only"),
            transaction.atomic(),
            connection.cursor() as cursor,
        ):
            cursor.execute(statement)
    assert len(rows()) == 1


def test_every_audit_action_passes_the_database_format_check(service):
    for action in AuditAction:
        service.write(
            AuditEvent(
                action=action, actor_type=ActorType.SYSTEM, actor_id=None, organization_id=None
            )
        )
    assert len(rows()) == len(AuditAction)
