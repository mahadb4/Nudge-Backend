"""Password endpoints. HTTP only: read the request, call ONE service method, map the result."""

from http import HTTPStatus

from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.dtos.password_dtos import (
    PasswordChangeRequest,
    ResetConfirmRequest,
    ResetRequest,
)
from common.api import CsrfProtectedApi, client_ip_of
from common.messages import Messages
from common.responses import accepted
from config import container
from config.authentication import principal_of


class PasswordChangeApi(APIView):
    """POST /auth/password/: 204. Bearer token; every other device is signed out."""

    def post(self, request: Request) -> Response:
        payload = PasswordChangeRequest.read(request.data)
        container.password_service().change(
            principal=principal_of(request), **payload, ip_address=client_ip_of(request)
        )
        return Response(status=HTTPStatus.NO_CONTENT)


class ResetRequestApi(CsrfProtectedApi):
    """POST /auth/reset/: 202 with the same body for every email."""

    def post(self, request: Request) -> Response:
        payload = ResetRequest.read(request.data)
        container.password_service().request_reset(**payload, ip_address=client_ip_of(request))
        return accepted(Messages.AUTH_RESET_LINK_SENT)


class ResetConfirmApi(CsrfProtectedApi):
    """POST /auth/reset/confirm/: 204. Every device is signed out."""

    def post(self, request: Request) -> Response:
        payload = ResetConfirmRequest.read(request.data)
        container.password_service().confirm_reset(**payload, ip_address=client_ip_of(request))
        return Response(status=HTTPStatus.NO_CONTENT)
