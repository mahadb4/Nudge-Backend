"""Exactly what the client may see from GET /api/v1/health/."""

from dataclasses import dataclass

from common.dtos import ResponseDto


@dataclass(frozen=True, slots=True)
class HealthResponse(ResponseDto):
    status: str
    database: str
