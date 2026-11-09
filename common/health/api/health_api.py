"""GET /api/v1/health/ (public). 200 {"status": "ok", "database": "ok"} or 503
COMMON_SERVICE_UNAVAILABLE."""

from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from common.health.mappers.health_mapper import to_health_response
from config import container


class HealthApi(APIView):
    authentication_classes: list[type] = []
    permission_classes: list[type] = []

    def get(self, request: Request) -> Response:
        report = container.health_service().check()
        return Response(to_health_response(report).to_dict())
