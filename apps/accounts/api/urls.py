from django.urls import path

from apps.accounts.api.auth_api import (
    CsrfApi,
    LoginApi,
    LogoutApi,
    MeApi,
    RefreshApi,
    RegisterApi,
    ResendApi,
    VerifyApi,
)
from apps.accounts.api.organization_api import CurrentOrganizationApi
from apps.accounts.api.password_api import PasswordChangeApi, ResetConfirmApi, ResetRequestApi

urlpatterns = [
    path("auth/csrf/", CsrfApi.as_view(), name="auth-csrf"),
    path("auth/register/", RegisterApi.as_view(), name="auth-register"),
    path("auth/verify/", VerifyApi.as_view(), name="auth-verify"),
    path("auth/resend/", ResendApi.as_view(), name="auth-resend"),
    path("auth/login/", LoginApi.as_view(), name="auth-login"),
    path("auth/refresh/", RefreshApi.as_view(), name="auth-refresh"),
    path("auth/logout/", LogoutApi.as_view(), name="auth-logout"),
    path("auth/me/", MeApi.as_view(), name="auth-me"),
    path("organizations/current/", CurrentOrganizationApi.as_view(), name="organization-current"),
    path("auth/password/", PasswordChangeApi.as_view(), name="auth-password"),
    path("auth/reset/", ResetRequestApi.as_view(), name="auth-reset"),
    path("auth/reset/confirm/", ResetConfirmApi.as_view(), name="auth-reset-confirm"),
]
