"""DRF authentication for the access token, wired here because the composition root may reach the
services. Every API class is authenticated unless it says otherwise (settings.py), so a new
endpoint is protected by default."""

from dataclasses import dataclass
from typing import ClassVar

from rest_framework.authentication import BaseAuthentication
from rest_framework.request import Request

from apps.accounts.domain.entities import Principal
from common.constants import MetaKey
from config import container

BEARER_REALM = "Bearer"


@dataclass(frozen=True, slots=True)
class AuthenticatedUser:
    """What DRF keeps in request.user. Carries the Principal and nothing else."""

    principal: Principal
    is_authenticated: ClassVar[bool] = True


class AccessTokenAuthentication(BaseAuthentication):
    def authenticate(self, request: Request) -> tuple[AuthenticatedUser, Principal] | None:
        header = request.META.get(MetaKey.AUTHORIZATION)
        if header is None:
            return None  # DRF then refuses the request with 401 (IsAuthenticated)
        principal = container.authentication_service().authenticate(header)
        return AuthenticatedUser(principal), principal

    def authenticate_header(self, request: Request) -> str:
        return BEARER_REALM


def principal_of(request: Request) -> Principal:
    """The signed-in user and session. Only call it from an authenticated API class."""
    return request.user.principal
