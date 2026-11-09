"""URL root. Every endpoint lives under /api/v1/. Errors outside DRF views are JSON as well."""

from django.urls import include, path, re_path

from common.responses import json_not_found

api_v1 = [
    path("", include("common.health.api.urls")),
    path("", include("apps.accounts.api.urls")),
    # Last: any unknown /api/v1/ path is a JSON 404, also with DEBUG=True (where handler404 is not
    # used).
    re_path(r"^.*$", json_not_found),
]

urlpatterns = [
    path("api/v1/", include(api_v1)),
]

handler400 = "common.responses.json_bad_request"
handler403 = "common.responses.json_forbidden"
handler404 = "common.responses.json_not_found"
handler500 = "common.responses.json_server_error"
