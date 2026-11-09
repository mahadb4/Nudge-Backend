"""What the audit service needs from storage. Writing only; reading comes after the midterm."""

from typing import Protocol
from uuid import UUID

from common.interfaces import AuditEvent


class AuditRepository(Protocol):
    def add(self, audit_id: UUID, event: AuditEvent) -> None:
        """Insert one row. There is no update and no delete: the table refuses both."""
        ...
