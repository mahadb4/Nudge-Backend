"""Business objects of crm. Frozen dataclasses, no framework."""

from dataclasses import dataclass
from uuid import UUID

from apps.crm.domain.enums import StageOutcome


@dataclass(frozen=True, slots=True)
class DealStage:
    id: UUID
    organization_id: UUID
    name: str
    position: int
    outcome: StageOutcome
