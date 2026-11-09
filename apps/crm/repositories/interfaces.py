"""What the crm services need from storage."""

from typing import Protocol
from uuid import UUID

from apps.crm.domain.entities import DealStage
from apps.crm.domain.enums import StageOutcome


class StageRepository(Protocol):
    def count(self, organization_id: UUID) -> int: ...

    def create(
        self,
        *,
        stage_id: UUID,
        organization_id: UUID,
        name: str,
        position: int,
        outcome: StageOutcome,
    ) -> DealStage: ...

    def list_for_organization(self, organization_id: UUID) -> list[DealStage]:
        """Ordered by position. At most 12 stages exist, so this list is not paginated."""
        ...
