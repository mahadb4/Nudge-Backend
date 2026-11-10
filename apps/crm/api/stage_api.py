"""Deal stage endpoints. Any member reads; Owner and Admin change."""

from http import HTTPStatus
from uuid import UUID

from rest_framework.request import Request
from rest_framework.response import Response

from apps.crm.dtos.stage_dtos import StageNameRequest, StageOrderRequest
from apps.crm.mappers.stage_mapper import to_stage_response
from common.api import client_ip_of
from common.constants import Role
from config import container
from config.tenancy import TenantApi, tenant_of


class DealStageApi(TenantApi):
    """GET /deal-stages/ and POST /deal-stages/."""

    write_roles = (Role.OWNER, Role.ADMIN)

    def get(self, request: Request) -> Response:
        stages = container.stage_service().list_stages(tenant_of(request))
        return Response([to_stage_response(s).to_dict() for s in stages])

    def post(self, request: Request) -> Response:
        stage = container.stage_service().create(
            tenant_of(request), StageNameRequest.read_sent(request.data), client_ip_of(request)
        )
        return Response(to_stage_response(stage).to_dict(), status=HTTPStatus.CREATED)


class DealStageDetailApi(TenantApi):
    """PATCH and DELETE /deal-stages/{id}/."""

    write_roles = (Role.OWNER, Role.ADMIN)

    def patch(self, request: Request, stage_id: UUID) -> Response:
        stage = container.stage_service().rename(
            tenant_of(request),
            stage_id,
            StageNameRequest.read_sent(request.data),
            client_ip_of(request),
        )
        return Response(to_stage_response(stage).to_dict())

    def delete(self, request: Request, stage_id: UUID) -> Response:
        container.stage_service().delete(tenant_of(request), stage_id, client_ip_of(request))
        return Response(status=HTTPStatus.NO_CONTENT)


class DealStageOrderApi(TenantApi):
    """PUT /deal-stages/order/: every stage id, in the new order."""

    write_roles = (Role.OWNER, Role.ADMIN)

    def put(self, request: Request) -> Response:
        stages = container.stage_service().reorder(
            tenant_of(request), StageOrderRequest.read_sent(request.data), client_ip_of(request)
        )
        return Response([to_stage_response(s).to_dict() for s in stages])
