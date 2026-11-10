"""GET and PATCH /organizations/current/. Any member reads; Owner and Admin edit."""

from rest_framework.request import Request
from rest_framework.response import Response

from apps.accounts.dtos.organization_dtos import OrganizationUpdateRequest
from apps.accounts.mappers.organization_mapper import to_organization_response
from common.api import client_ip_of
from common.constants import Role
from config import container
from config.tenancy import TenantApi, tenant_of


class CurrentOrganizationApi(TenantApi):
    write_roles = (Role.OWNER, Role.ADMIN)

    def get(self, request: Request) -> Response:
        organization = container.organization_service().get_current(tenant_of(request))
        return Response(to_organization_response(organization).to_dict())

    def patch(self, request: Request) -> Response:
        sent = OrganizationUpdateRequest.read_sent(request.data)
        organization = container.organization_service().update_current(
            tenant_of(request), sent, client_ip_of(request)
        )
        return Response(to_organization_response(organization).to_dict())
