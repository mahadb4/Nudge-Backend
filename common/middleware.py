"""API responses are never cached by browsers or proxies (SECURITY.md: Cache-Control: no-store)."""

from collections.abc import Callable

from django.http import HttpRequest, HttpResponse

from common.constants import API_PREFIX, Header, HeaderValue


class NoStoreApiMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        response = self.get_response(request)
        if request.path.startswith(API_PREFIX):
            response[Header.CACHE_CONTROL] = HeaderValue.NO_STORE
        return response
