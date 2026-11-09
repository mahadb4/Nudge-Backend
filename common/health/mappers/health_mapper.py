"""Entity -> response DTO. A pure function."""

from common.constants import HealthStatus
from common.health.domain.entities import HealthReport
from common.health.dtos.health_dtos import HealthResponse


def to_health_response(report: HealthReport) -> HealthResponse:
    return HealthResponse(
        status=HealthStatus.OK,
        database=HealthStatus.OK if report.database_ok else HealthStatus.DOWN,
    )
