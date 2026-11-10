"""Company endpoints. Any member of the organization; the visibility rule decides which rows."""

from http import HTTPStatus
from uuid import UUID

from rest_framework.request import Request
from rest_framework.response import Response

from apps.crm.domain.errors import StaleCompany
from apps.crm.dtos.company_dtos import ORDERINGS, CompanyCreateRequest, CompanyUpdateRequest
from apps.crm.mappers.company_mapper import to_company_page_response, to_company_response
from common.api import client_ip_of
from common.errors import Conflict
from common.messages import Messages
from common.pagination import PARAM_PAGE, page_link, parse_list_query
from common.validators import validate_uuid
from config import container
from config.tenancy import TenantApi, tenant_of


def _query_dict(request: Request) -> dict[str, str]:
    return {key: request.query_params[key] for key in request.query_params}


class CompanyListApi(TenantApi):
    """GET /companies/ (page, page_size, q, owner_id, ordering) and POST /companies/."""

    def get(self, request: Request) -> Response:
        params = _query_dict(request)
        query = parse_list_query(
            params,
            orderings=ORDERINGS,
            default_ordering="name",
            filters={"owner_id": validate_uuid},
        )
        page = container.company_service().list_companies(tenant_of(request), query)
        base = request.build_absolute_uri(request.path)
        params.pop(PARAM_PAGE, None)
        next_link = page_link(base, params, query.page + 1) if page.has_next else None
        previous = page_link(base, params, query.page - 1) if page.has_previous else None
        return Response(to_company_page_response(page, next_link, previous).to_dict())

    def post(self, request: Request) -> Response:
        company = container.company_service().create(
            tenant_of(request), CompanyCreateRequest.read_sent(request.data), client_ip_of(request)
        )
        return Response(to_company_response(company).to_dict(), status=HTTPStatus.CREATED)


class CompanyApi(TenantApi):
    """GET, PATCH and DELETE /companies/{id}/."""

    def get(self, request: Request, company_id: UUID) -> Response:
        company = container.company_service().get_company(tenant_of(request), company_id)
        return Response(to_company_response(company).to_dict())

    def patch(self, request: Request, company_id: UUID) -> Response:
        try:
            company = container.company_service().update(
                tenant_of(request),
                company_id,
                CompanyUpdateRequest.read_sent(request.data),
                client_ip_of(request),
            )
        except StaleCompany as stale:
            raise Conflict(
                Messages.COMMON_VERSION_CONFLICT,
                current=to_company_response(stale.current).to_dict(),  # type: ignore[arg-type]
            ) from None
        return Response(to_company_response(company).to_dict())

    def delete(self, request: Request, company_id: UUID) -> Response:
        container.company_service().delete(tenant_of(request), company_id, client_ip_of(request))
        return Response(status=HTTPStatus.NO_CONTENT)
