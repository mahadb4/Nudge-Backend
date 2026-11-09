"""The AuditWriter other modules use. They depend on the Protocol in common/interfaces.py, never on
this module."""

from apps.audit.repositories.interfaces import AuditRepository
from common.interfaces import AuditEvent, IdGenerator


class AuditService:
    def __init__(self, repository: AuditRepository, ids: IdGenerator) -> None:
        self._repository = repository
        self._ids = ids

    def write(self, event: AuditEvent) -> None:
        # Callers put no passwords, tokens, codes or email addresses in event.details (a hash is
        # fine).
        self._repository.add(self._ids.new_id(), event)
