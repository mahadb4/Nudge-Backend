"""Request and response shapes of the auth endpoints, together (CODING_STYLE 1).

Requests are strict serializers: unknown fields are refused and values reach the validators
untouched.
Responses are small frozen dataclasses with to_dict(): exactly what the client may see.
"""

from dataclasses import dataclass

from common.dtos import ResponseDto
from common.serializers import StrictSerializer, raw_field


class RegisterRequest(StrictSerializer):
    name = raw_field()
    company = raw_field()
    email = raw_field()
    password = raw_field()
    type = raw_field(source="account_type")  # the frontend calls it "type"
    timezone = raw_field()


class VerifyRequest(StrictSerializer):
    email = raw_field()
    code = raw_field()


class LoginRequest(StrictSerializer):
    email = raw_field()
    password = raw_field()
    remember = raw_field()


class ResendRequest(StrictSerializer):
    email = raw_field()


@dataclass(frozen=True, slots=True)
class CsrfResponse(ResponseDto):
    csrf_token: str


@dataclass(frozen=True, slots=True)
class MeOrganization(ResponseDto):
    id: str
    name: str
    type: str
    timezone: str


@dataclass(frozen=True, slots=True)
class MeOrganizationRef(ResponseDto):
    id: str
    name: str
    role: str


@dataclass(frozen=True, slots=True)
class MeResponse(ResponseDto):
    id: str
    name: str
    email: str
    type: str
    verified: bool
    phone: str | None
    timezone: str
    organization: MeOrganization
    role: str
    organizations: list[MeOrganizationRef]


@dataclass(frozen=True, slots=True)
class SignInResponse(ResponseDto):
    access: str
    user: MeResponse
