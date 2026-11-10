"""Request and response shapes of the deal stage endpoints."""

from dataclasses import dataclass

from common.dtos import ResponseDto
from common.serializers import StrictSerializer, raw_field


class StageNameRequest(StrictSerializer):
    name = raw_field()


class StageOrderRequest(StrictSerializer):
    ids = raw_field()


@dataclass(frozen=True, slots=True)
class StageResponse(ResponseDto):
    id: str
    name: str
    position: int
    outcome: str
    deal_count: int
