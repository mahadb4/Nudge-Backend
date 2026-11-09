"""What accounts needs from other modules. Owned here (by the user of the service); crm implements
it."""

from collections.abc import Sequence
from typing import Protocol
from uuid import UUID


class DefaultStageSeeder(Protocol):
    def seed_defaults(self, organization_id: UUID) -> Sequence[object]:
        """Give a new organization its default deal stages. Safe to call twice."""
        ...
