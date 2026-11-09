"""What the health check found. A plain value, no framework."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class HealthReport:
    database_ok: bool
