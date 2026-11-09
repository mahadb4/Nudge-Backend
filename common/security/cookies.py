"""The refresh token cookie: HttpOnly, Lax, scoped to the auth endpoints, Secure outside local
development."""

from django.conf import settings
from django.http import HttpResponse

from common.constants import SECURE_COOKIE_SAMESITE, Cookie


def set_refresh_cookie(response: HttpResponse, value: str, max_age: int | None) -> None:
    # max_age None = a session cookie (gone when the browser closes); 'keep me signed in' sets it.
    response.set_cookie(
        Cookie.REFRESH,
        value,
        max_age=max_age,
        path=Cookie.REFRESH_PATH,
        secure=settings.REFRESH_COOKIE_SECURE,
        httponly=True,
        samesite=SECURE_COOKIE_SAMESITE,
    )


def clear_refresh_cookie(response: HttpResponse) -> None:
    response.delete_cookie(
        Cookie.REFRESH, path=Cookie.REFRESH_PATH, samesite=SECURE_COOKIE_SAMESITE
    )
