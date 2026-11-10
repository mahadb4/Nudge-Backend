"""Request and response shapes of /organizations/current/."""

from dataclasses import dataclass

from common.dtos import ResponseDto
from common.serializers import StrictSerializer, raw_field


class OrganizationUpdateRequest(StrictSerializer):
    name = raw_field()
    timezone = raw_field()


@dataclass(frozen=True, slots=True)
class OrganizationResponse(ResponseDto):
    id: str
    name: str
    type: str
    timezone: str
    automation_paused: bool
