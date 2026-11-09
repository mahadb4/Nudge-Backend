"""Auth endpoints. HTTP only: read the request, call ONE service method, map the result."""

from http import HTTPStatus

from django.middleware.csrf import get_token
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.dtos.auth_dtos import (
    CsrfResponse,
    LoginRequest,
    RegisterRequest,
    ResendRequest,
    VerifyRequest,
)
from apps.accounts.mappers.auth_mapper import to_me_response, to_sign_in_response
from common.api import CsrfProtectedApi, client_ip_of
from common.constants import Cookie, MetaKey
from common.errors import Unauthorized
from common.messages import Messages
from common.responses import accepted, error_response
from common.security.cookies import clear_refresh_cookie, set_refresh_cookie
from config import container
from config.authentication import principal_of


class CsrfApi(APIView):
    """GET /auth/csrf/: hands out the CSRF token. Django's middleware sets the csrftoken cookie on
    the reply."""

    authentication_classes: list[type] = []
    permission_classes: list[type] = []

    def get(self, request: Request) -> Response:
        return Response(CsrfResponse(csrf_token=get_token(request._request)).to_dict())


class RegisterApi(CsrfProtectedApi):
    """POST /auth/register/: 202 with the same body for every email."""

    def post(self, request: Request) -> Response:
        payload = RegisterRequest.read(request.data)
        container.registration_service().register(**payload, ip_address=client_ip_of(request))
        return accepted(Messages.AUTH_CODE_SENT)


class VerifyApi(CsrfProtectedApi):
    """POST /auth/verify/: 200 {access, user} and the refresh cookie."""

    def post(self, request: Request) -> Response:
        payload = VerifyRequest.read(request.data)
        result = container.verification_service().verify(
            **payload, ip_address=client_ip_of(request)
        )
        response = Response(to_sign_in_response(result).to_dict())
        set_refresh_cookie(response, result.tokens.refresh_value, result.tokens.cookie_max_age)
        return response


class ResendApi(CsrfProtectedApi):
    """POST /auth/resend/: 202 with the same body for every email."""

    def post(self, request: Request) -> Response:
        payload = ResendRequest.read(request.data)
        container.verification_service().resend(**payload, ip_address=client_ip_of(request))
        return accepted(Messages.AUTH_CODE_SENT)


class LoginApi(CsrfProtectedApi):
    """POST /auth/login/: 200 {access, user} and the refresh cookie."""

    def post(self, request: Request) -> Response:
        payload = LoginRequest.read(request.data)
        result = container.sign_in_service().login(
            **payload,
            ip_address=client_ip_of(request),
            user_agent=request.META.get(MetaKey.USER_AGENT),
        )
        response = Response(to_sign_in_response(result).to_dict())
        set_refresh_cookie(response, result.tokens.refresh_value, result.tokens.cookie_max_age)
        return response


class RefreshApi(CsrfProtectedApi):
    """POST /auth/refresh/: no body. Rotates the refresh cookie; a refused session loses its
    cookie."""

    def post(self, request: Request) -> Response:
        try:
            result = container.sign_in_service().refresh(
                refresh_value=request.COOKIES.get(Cookie.REFRESH),
                ip_address=client_ip_of(request),
            )
        except Unauthorized as err:
            response = error_response(err)
            clear_refresh_cookie(response)
            return response
        response = Response(to_sign_in_response(result).to_dict())
        set_refresh_cookie(response, result.tokens.refresh_value, result.tokens.cookie_max_age)
        return response


class LogoutApi(CsrfProtectedApi):
    """POST /auth/logout/: 204 always, and the cookie is cleared."""

    def post(self, request: Request) -> Response:
        container.sign_in_service().logout(
            refresh_value=request.COOKIES.get(Cookie.REFRESH), ip_address=client_ip_of(request)
        )
        response = Response(status=HTTPStatus.NO_CONTENT)
        clear_refresh_cookie(response)
        return response


class MeApi(APIView):
    """GET /auth/me/: the signed-in user (bearer token)."""

    def get(self, request: Request) -> Response:
        me = container.me_service().get_me(principal_of(request).user_id)
        return Response(to_me_response(me).to_dict())
