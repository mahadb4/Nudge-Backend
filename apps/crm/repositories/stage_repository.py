"""deal_stages table. Every query filters by organization."""

from uuid import UUID

from apps.crm.domain.entities import DealStage
from apps.crm.domain.enums import StageOutcome
from apps.crm.repositories.models import DealStageModel


def _to_entity(row: DealStageModel) -> DealStage:
    return DealStage(
        id=row.id,
        organization_id=row.organization_id,
        name=row.name,
        position=row.position,
        outcome=StageOutcome(row.outcome),
    )


class PostgresStageRepository:
    def count(self, organization_id: UUID) -> int:
        return DealStageModel.objects.filter(organization_id=organization_id).count()

    def create(
        self,
        *,
        stage_id: UUID,
        organization_id: UUID,
        name: str,
        position: int,
        outcome: StageOutcome,
    ) -> DealStage:
        row = DealStageModel.objects.create(
            id=stage_id,
            organization_id=organization_id,
            name=name,
            position=position,
            outcome=int(outcome),
        )
        return _to_entity(row)

    def list_for_organization(self, organization_id: UUID) -> list[DealStage]:
        rows = DealStageModel.objects.filter(organization_id=organization_id).order_by(
            "position", "id"
        )
        return [_to_entity(row) for row in rows]
