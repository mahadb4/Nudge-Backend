"""deal_stages table. Tenant-scoped: every method takes the TenantContext first and every query
starts from _rows(context)."""

from collections.abc import Sequence
from uuid import UUID

from django.db import IntegrityError, transaction
from django.db.models import Count
from django.db.models.functions import Now

from apps.crm.domain.entities import DealStage, StageSummary
from apps.crm.domain.enums import StageOutcome
from apps.crm.domain.errors import DuplicateStageName
from apps.crm.repositories.models import DealModel, DealStageModel
from common.tenancy import TenantContext
from common.tenant_repository import TenantRepository

UNIQUE_NAME_INDEX = "uq_deal_stages_1"


def _to_entity(row: DealStageModel) -> DealStage:
    return DealStage(
        id=row.id,
        organization_id=row.organization_id,
        name=row.name,
        position=row.position,
        outcome=StageOutcome(row.outcome),
    )


def _is_duplicate_name(error: IntegrityError) -> bool:
    diag = getattr(error.__cause__, "diag", None)
    return getattr(diag, "constraint_name", None) == UNIQUE_NAME_INDEX


class PostgresStageRepository(TenantRepository[DealStageModel]):
    model = DealStageModel

    def count(self, context: TenantContext) -> int:
        return self._rows(context).count()

    def list_all(self, context: TenantContext) -> list[DealStage]:
        return [_to_entity(row) for row in self._rows(context).order_by("position", "id")]

    def list_with_counts(self, context: TenantContext) -> list[StageSummary]:
        """Two queries however many stages exist: the stages, then the live deal counts."""
        stages = self.list_all(context)
        counts = dict(
            DealModel.objects.filter(
                organization_id=context.organization_id, deleted_at__isnull=True
            )
            .values_list("stage_id")
            .annotate(total=Count("id"))
        )
        return [StageSummary(stage, counts.get(stage.id, 0)) for stage in stages]

    def lock_all(self, context: TenantContext) -> list[DealStage]:
        """All stages of the organization, locked until the transaction ends. Needs an open
        transaction. Serialises concurrent stage edits and deal moves."""
        rows = self._rows(context).select_for_update().order_by("position", "id")
        return [_to_entity(row) for row in rows]

    def create(
        self,
        context: TenantContext,
        *,
        stage_id: UUID,
        name: str,
        position: int,
        outcome: StageOutcome,
    ) -> DealStage:
        try:
            # A savepoint: a duplicate name does not poison the caller's transaction.
            with transaction.atomic():
                row = DealStageModel.objects.create(
                    id=stage_id,
                    organization_id=context.organization_id,
                    name=name,
                    position=position,
                    outcome=int(outcome),
                )
        except IntegrityError as exc:
            if _is_duplicate_name(exc):
                raise DuplicateStageName() from exc
            raise
        return _to_entity(row)

    def rename(self, context: TenantContext, stage_id: UUID, name: str) -> None:
        try:
            with transaction.atomic():
                self._rows(context).filter(id=stage_id).update(name=name, updated_at=Now())
        except IntegrityError as exc:
            if _is_duplicate_name(exc):
                raise DuplicateStageName() from exc
            raise

    def set_positions(self, context: TenantContext, ordered_ids: Sequence[UUID]) -> None:
        """Positions become 0..n-1 in the given order (at most 12 rows)."""
        for position, stage_id in enumerate(ordered_ids):
            self._rows(context).filter(id=stage_id).update(position=position, updated_at=Now())

    def delete(self, context: TenantContext, stage_id: UUID) -> bool:
        deleted, _ = self._rows(context).filter(id=stage_id).delete()
        return deleted == 1

    def count_deals(self, context: TenantContext, stage_id: UUID) -> int:
        """Every deal that points at the stage, also soft-deleted ones: the foreign key still
        refuses the delete for those."""
        return DealModel.objects.filter(
            organization_id=context.organization_id, stage_id=stage_id
        ).count()
