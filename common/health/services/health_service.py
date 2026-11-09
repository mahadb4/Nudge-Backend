"""Health use case. Knows nothing about HTTP or SQL."""

from common.errors import ServiceUnavailable
from common.health.domain.entities import HealthReport
from common.health.repositories.interfaces import HealthRepository


class HealthService:
    def __init__(self, repository: HealthRepository) -> None:
        self._repository = repository

    def check(self) -> HealthReport:
        if not self._repository.is_database_available():
            raise ServiceUnavailable()
        return HealthReport(database_ok=True)
