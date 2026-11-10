"""Request and response shapes of the company endpoints."""

from dataclasses import dataclass

from common.dtos import ResponseDto
from common.serializers import StrictSerializer, raw_field

ORDERINGS = ("name", "-created_at")  # ?ordering= allowlist; the repository maps each to columns


class CompanyCreateRequest(StrictSerializer):
    name = raw_field()
    domain = raw_field()
    industry = raw_field()
    size_range = raw_field()
    owner_id = raw_field()
    visibility = raw_field()
    team_id = raw_field()


class CompanyUpdateRequest(CompanyCreateRequest):
    updated_at = raw_field()


@dataclass(frozen=True, slots=True)
class CompanyOwner(ResponseDto):
    id: str
    name: str


@dataclass(frozen=True, slots=True)
class MoneyResponse(ResponseDto):
    currency: str
    amount: str


@dataclass(frozen=True, slots=True)
class CompanyResponse(ResponseDto):
    id: str
    name: str
    domain: str | None
    industry: str | None
    size_range: str | None
    owner: CompanyOwner
    visibility: str
    team_id: str | None
    people_count: int
    open_deal_count: int
    open_value: list[MoneyResponse]
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class CompanyPageResponse(ResponseDto):
    count: int
    next: str | None
    previous: str | None
    results: list[CompanyResponse]
