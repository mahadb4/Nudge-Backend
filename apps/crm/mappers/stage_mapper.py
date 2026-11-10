"""Stage entities -> response DTOs."""

from types import MappingProxyType

from apps.crm.domain.entities import StageSummary
from apps.crm.domain.enums import StageOutcome
from apps.crm.dtos.stage_dtos import StageResponse

OUTCOME_WIRE = MappingProxyType(
    {StageOutcome.OPEN: "open", StageOutcome.WON: "won", StageOutcome.LOST: "lost"}
)


def to_stage_response(summary: StageSummary) -> StageResponse:
    stage = summary.stage
    return StageResponse(
        id=str(stage.id),
        name=stage.name,
        position=stage.position,
        outcome=OUTCOME_WIRE[stage.outcome],
        deal_count=summary.deal_count,
    )
