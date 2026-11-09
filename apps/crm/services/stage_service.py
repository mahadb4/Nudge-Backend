"""Deal stage use cases. For now only what sign-up needs: give a new organization its default
stages."""

from uuid import UUID

from apps.crm.domain.defaults import DEFAULT_STAGES
from apps.crm.domain.entities import DealStage
from apps.crm.repositories.interfaces import StageRepository
from common.interfaces import IdGenerator


class StageService:
    def __init__(self, stages: StageRepository, ids: IdGenerator) -> None:
        self._stages = stages
        self._ids = ids

    def seed_defaults(self, organization_id: UUID) -> list[DealStage]:
        """Create the seven default stages. Does nothing if the organization already has stages
        (safe to repeat)."""
        if self._stages.count(organization_id) > 0:
            return self._stages.list_for_organization(organization_id)
        return [
            self._stages.create(
                stage_id=self._ids.new_id(),
                organization_id=organization_id,
                name=name,
                position=position,
                outcome=outcome,
            )
            for position, (name, outcome) in enumerate(DEFAULT_STAGES)
        ]
