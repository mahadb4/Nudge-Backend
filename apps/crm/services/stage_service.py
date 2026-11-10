"""Deal stage use cases: the default stages for a new organization, and list, create, rename,
reorder and delete (Q-5). Every change runs in one transaction with the stages locked, and is
audited."""

from collections.abc import Sequence
from uuid import UUID

from apps.crm.domain.defaults import DEFAULT_STAGES
from apps.crm.domain.entities import DealStage, StageSummary
from apps.crm.domain.enums import StageOutcome
from apps.crm.domain.errors import DuplicateStageName
from apps.crm.repositories.interfaces import StageRepository
from apps.crm.services.stage_validator import StageValidator
from common.constants import ActorType, AuditAction, Limits
from common.errors import Conflict, FieldIssue, NotFound, ValidationFailed
from common.interfaces import AuditEvent, AuditWriter, IdGenerator, UnitOfWork
from common.messages import Messages
from common.permissions import OWNER_OR_ADMIN, require_role
from common.tenancy import TenantContext

AUDIT_OBJECT_STAGE = "deal_stage"


class StageService:
    def __init__(
        self,
        stages: StageRepository,
        ids: IdGenerator,
        audit: AuditWriter,
        uow: UnitOfWork,
        validator: StageValidator,
    ) -> None:
        self._stages = stages
        self._ids = ids
        self._audit = audit
        self._uow = uow
        self._validator = validator

    def seed_defaults(self, context: TenantContext) -> list[DealStage]:
        """Create the seven default stages. Does nothing if the organization already has stages
        (safe to repeat)."""
        if self._stages.count(context) > 0:
            return self._stages.list_all(context)
        return [
            self._stages.create(
                context,
                stage_id=self._ids.new_id(),
                name=name,
                position=position,
                outcome=outcome,
            )
            for position, (name, outcome) in enumerate(DEFAULT_STAGES)
        ]

    def list_stages(self, context: TenantContext) -> list[StageSummary]:
        return self._stages.list_with_counts(context)

    def create(
        self, context: TenantContext, sent: dict[str, object], ip_address: str | None
    ) -> StageSummary:
        require_role(context, OWNER_OR_ADMIN)
        name = self._validator.validate_name(sent)
        with self._uow.atomic():
            stages = self._stages.lock_all(context)
            if len(stages) >= Limits.STAGES_MAX:
                raise ValidationFailed(Messages.CRM_STAGE_LIMIT_REACHED, Limits.STAGES_MAX)
            if _name_taken(stages, name, except_id=None):
                raise Conflict(Messages.CRM_STAGE_NAME_TAKEN)
            # A new stage is open, so it goes in front of the first Won or Lost stage.
            at = next(
                (i for i, s in enumerate(stages) if s.outcome is not StageOutcome.OPEN), len(stages)
            )
            try:
                stage = self._stages.create(
                    context,
                    stage_id=self._ids.new_id(),
                    name=name,
                    position=at,
                    outcome=StageOutcome.OPEN,
                )
            except DuplicateStageName:
                raise Conflict(Messages.CRM_STAGE_NAME_TAKEN) from None
            order = [s.id for s in stages]
            order.insert(at, stage.id)
            self._stages.set_positions(context, order)
            self._record(
                context, AuditAction.DEAL_STAGE_CREATE, stage.id, {"name": name}, ip_address
            )
        return StageSummary(DealStage(stage.id, stage.organization_id, name, at, stage.outcome), 0)

    def rename(
        self,
        context: TenantContext,
        stage_id: UUID,
        sent: dict[str, object],
        ip_address: str | None,
    ) -> StageSummary:
        require_role(context, OWNER_OR_ADMIN)
        name = self._validator.validate_name(sent)
        with self._uow.atomic():
            stages = self._stages.lock_all(context)
            stage = _find(stages, stage_id)
            if stage.outcome is not StageOutcome.OPEN:
                raise ValidationFailed(Messages.CRM_STAGE_FIXED)
            if _name_taken(stages, name, except_id=stage.id):
                raise Conflict(Messages.CRM_STAGE_NAME_TAKEN)
            if name != stage.name:
                try:
                    self._stages.rename(context, stage.id, name)
                except DuplicateStageName:
                    raise Conflict(Messages.CRM_STAGE_NAME_TAKEN) from None
                self._record(
                    context,
                    AuditAction.DEAL_STAGE_UPDATE,
                    stage.id,
                    {"from": stage.name, "to": name},
                    ip_address,
                )
        return next(s for s in self._stages.list_with_counts(context) if s.stage.id == stage_id)

    def reorder(
        self, context: TenantContext, sent: dict[str, object], ip_address: str | None
    ) -> list[StageSummary]:
        require_role(context, OWNER_OR_ADMIN)
        wanted = self._validator.validate_order(sent)
        with self._uow.atomic():
            stages = self._stages.lock_all(context)
            _check_order(stages, wanted)
            if wanted != [s.id for s in stages]:
                self._stages.set_positions(context, wanted)
                self._record(
                    context,
                    AuditAction.DEAL_STAGE_REORDER,
                    None,
                    {"count": len(wanted)},
                    ip_address,
                )
        return self._stages.list_with_counts(context)

    def delete(self, context: TenantContext, stage_id: UUID, ip_address: str | None) -> None:
        require_role(context, OWNER_OR_ADMIN)
        with self._uow.atomic():
            stages = self._stages.lock_all(context)
            stage = _find(stages, stage_id)
            if stage.outcome is not StageOutcome.OPEN:
                raise ValidationFailed(Messages.CRM_STAGE_FIXED)
            if self._stages.count_deals(context, stage.id) > 0:
                raise Conflict(Messages.CRM_STAGE_IN_USE)
            if sum(1 for s in stages if s.outcome is StageOutcome.OPEN) == 1:
                raise Conflict(Messages.CRM_LAST_OPEN_STAGE)
            self._stages.delete(context, stage.id)
            # Positions stay 0..n-1 without gaps.
            self._stages.set_positions(context, [s.id for s in stages if s.id != stage.id])
            self._record(
                context, AuditAction.DEAL_STAGE_DELETE, stage.id, {"name": stage.name}, ip_address
            )

    def _record(
        self,
        context: TenantContext,
        action: AuditAction,
        stage_id: UUID | None,
        details: dict[str, object],
        ip_address: str | None,
    ) -> None:
        self._audit.write(
            AuditEvent(
                action=action,
                actor_type=ActorType.USER,
                actor_id=context.user_id,
                organization_id=context.organization_id,
                object_type=AUDIT_OBJECT_STAGE,
                object_id=stage_id,
                details=details,
                ip_address=ip_address,
            )
        )


def _find(stages: Sequence[DealStage], stage_id: UUID) -> DealStage:
    # The stages were read for this organization only, so another organization's id is 404.
    found = next((s for s in stages if s.id == stage_id), None)
    if found is None:
        raise NotFound()
    return found


def _name_taken(stages: Sequence[DealStage], name: str, *, except_id: UUID | None) -> bool:
    return any(s.name.casefold() == name.casefold() and s.id != except_id for s in stages)


def _check_order(stages: Sequence[DealStage], wanted: Sequence[UUID]) -> None:
    """Every stage exactly once; the first open stage stays first; open stages, then Won, then
    Lost."""
    current = {s.id: s for s in stages}
    valid = (
        bool(wanted)
        and len(wanted) == len(set(wanted))
        and set(wanted) == set(current)
        and wanted[0] == stages[0].id
        and all(
            current[a].outcome <= current[b].outcome
            for a, b in zip(wanted, wanted[1:], strict=False)
        )
    )
    if not valid:
        raise ValidationFailed(fields={"ids": [FieldIssue(Messages.CRM_STAGE_ORDER_INVALID)]})
