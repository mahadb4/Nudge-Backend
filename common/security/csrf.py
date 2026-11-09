"""CSRF double submit for cookie endpoints: the csrftoken cookie must match the X-CSRFToken header.

DRF views skip Django's CSRF middleware, so the check is run by hand with Django's own
implementation.
"""

from django.http import HttpRequest, HttpResponse
from django.middleware.csrf import CsrfViewMiddleware

from common.errors import Forbidden
from common.messages import Messages


class _CsrfCheck(CsrfViewMiddleware):
    def _reject(self, request: HttpRequest, reason: str) -> str:  # type: ignore[override]
        return reason


def _no_response(request: HttpRequest) -> HttpResponse:
    raise NotImplementedError


def enforce_csrf(request: HttpRequest) -> None:
    # Use the plain Django request under DRF's wrapper, so the body is not parsed early.
    plain = getattr(request, "_request", request)
    check = _CsrfCheck(_no_response)
    check.process_request(plain)
    if check.process_view(plain, None, (), {}):
        raise Forbidden(Messages.AUTH_CSRF_FAILED)
