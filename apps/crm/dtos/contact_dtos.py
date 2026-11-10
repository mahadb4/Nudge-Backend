"""Request and response shapes of the contact endpoints."""

from dataclasses import dataclass

from common.dtos import ResponseDto
from common.serializers import StrictSerializer, raw_field

ORDERINGS = ("name", "-created_at")  # ?ordering= allowlist; the repository maps each to columns


class ContactCreateRequest(StrictSerializer):
    first_name = raw_field()
    last_name = raw_field()
    email = raw_field()
    phone = raw_field()
    title = raw_field()
    company_id = raw_field()
    owner_id = raw_field()
    visibility = raw_field()
    team_id = raw_field()


class ContactUpdateRequest(ContactCreateRequest):
    updated_at = raw_field()


@dataclass(frozen=True, slots=True)
class ContactCompany(ResponseDto):
    id: str
    name: str


@dataclass(frozen=True, slots=True)
class ContactOwner(ResponseDto):
    id: str
    name: str


@dataclass(frozen=True, slots=True)
class ContactResponse(ResponseDto):
    id: str
    first_name: str
    last_name: str | None
    name: str
    email: str | None
    phone: str | None
    title: str | None
    company: ContactCompany | None
    owner: ContactOwner
    visibility: str
    team_id: str | None
    status: str
    opted_out_at: str | None
    source: str
    last_contact_at: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class ContactPageResponse(ResponseDto):
    count: int
    next: str | None
    previous: str | None
    results: list[ContactResponse]
