"""Base classes and helpers for API classes (the HTTP layer)."""

from django.conf import settings
from rest_framework.request import Request
from rest_framework.views import APIView

from common.constants import MetaKey
from common.security.client_ip import client_ip
from common.security.csrf import enforce_csrf


def client_ip_of(request: Request) -> str | None:
    meta = request.META
    return client_ip(
        meta.get(MetaKey.REMOTE_ADDR), meta.get(MetaKey.FORWARDED_FOR), settings.TRUSTED_PROXIES
    )


class CsrfProtectedApi(APIView):
    """Public endpoints that set or read a cookie: no login needed, but the CSRF double submit is
    required."""

    authentication_classes: list[type] = []
    permission_classes: list[type] = []

    def initial(self, request: Request, *args: object, **kwargs: object) -> None:
        super().initial(request, *args, **kwargs)
        enforce_csrf(request)
