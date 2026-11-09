"""audit_logs table. Insert only."""

from uuid import UUID

from apps.audit.repositories.models import AuditLogModel
from common.interfaces import AuditEvent


class PostgresAuditRepository:
    def add(self, audit_id: UUID, event: AuditEvent) -> None:
        AuditLogModel.objects.create(
            id=audit_id,
            organization_id=event.organization_id,
            actor_id=event.actor_id,
            actor_type=int(event.actor_type),
            action=str(event.action),
            object_type=event.object_type,
            object_id=event.object_id,
            details=dict(event.details),
            ip_address=event.ip_address,
        )
