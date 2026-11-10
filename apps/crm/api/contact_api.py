"""Contact endpoints. Any member of the organization; the visibility rule decides which rows."""

from http import HTTPStatus
from uuid import UUID

from rest_framework.request import Request
from rest_framework.response import Response

from apps.crm.domain.enums import CONTACT_STATUS_BY_WIRE
from apps.crm.domain.errors import ContactEmailTaken, StaleContact
from apps.crm.dtos.contact_dtos import ORDERINGS, ContactCreateRequest, ContactUpdateRequest
from apps.crm.mappers.contact_mapper import to_contact_page_response, to_contact_response
from common.api import client_ip_of
from common.errors import Conflict
from common.messages import Messages
from common.pagination import PARAM_PAGE, page_link, parse_list_query
from common.validators import validate_choice, validate_uuid
from config import container
from config.tenancy import TenantApi, tenant_of


def _query_dict(request: Request) -> dict[str, str]:
    return {key: request.query_params[key] for key in request.query_params}


def _status(raw: object) -> bool:
    return validate_choice(raw, CONTACT_STATUS_BY_WIRE)


class ContactListApi(TenantApi):
    """GET /contacts/ (page, page_size, q, status, owner_id, company_id, ordering) and POST."""

    def get(self, request: Request) -> Response:
        params = _query_dict(request)
        query = parse_list_query(
            params,
            orderings=ORDERINGS,
            default_ordering="name",
            filters={"owner_id": validate_uuid, "company_id": validate_uuid, "status": _status},
        )
        page = container.contact_service().list_contacts(tenant_of(request), query)
        base = request.build_absolute_uri(request.path)
        params.pop(PARAM_PAGE, None)
        next_link = page_link(base, params, query.page + 1) if page.has_next else None
        previous = page_link(base, params, query.page - 1) if page.has_previous else None
        return Response(to_contact_page_response(page, next_link, previous).to_dict())

    def post(self, request: Request) -> Response:
        try:
            contact = container.contact_service().create(
                tenant_of(request),
                ContactCreateRequest.read_sent(request.data),
                client_ip_of(request),
            )
        except ContactEmailTaken as taken:
            raise _email_conflict(taken) from None
        return Response(to_contact_response(contact).to_dict(), status=HTTPStatus.CREATED)


class ContactApi(TenantApi):
    """GET, PATCH and DELETE /contacts/{id}/."""

    def get(self, request: Request, contact_id: UUID) -> Response:
        contact = container.contact_service().get_contact(tenant_of(request), contact_id)
        return Response(to_contact_response(contact).to_dict())

    def patch(self, request: Request, contact_id: UUID) -> Response:
        try:
            contact = container.contact_service().update(
                tenant_of(request),
                contact_id,
                ContactUpdateRequest.read_sent(request.data),
                client_ip_of(request),
            )
        except StaleContact as stale:
            raise Conflict(
                Messages.COMMON_VERSION_CONFLICT,
                current=to_contact_response(stale.current).to_dict(),  # type: ignore[arg-type]
            ) from None
        except ContactEmailTaken as taken:
            raise _email_conflict(taken) from None
        return Response(to_contact_response(contact).to_dict())

    def delete(self, request: Request, contact_id: UUID) -> Response:
        container.contact_service().delete(tenant_of(request), contact_id, client_ip_of(request))
        return Response(status=HTTPStatus.NO_CONTENT)


def _email_conflict(taken: ContactEmailTaken) -> Conflict:
    """409; "existing" is only there when the caller may see the other contact."""
    extra: dict[str, object] = {}
    if taken.existing is not None:
        existing = to_contact_response(taken.existing)  # type: ignore[arg-type]
        extra["existing"] = {"id": existing.id, "name": existing.name}
    return Conflict(Messages.CRM_CONTACT_EMAIL_TAKEN, extra=extra)
