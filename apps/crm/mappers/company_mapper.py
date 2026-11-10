"""Company entities -> response DTOs."""

from apps.crm.domain.entities import CompanyDetails
from apps.crm.domain.enums import COMPANY_SIZE_WIRE, VISIBILITY_WIRE
from apps.crm.dtos.company_dtos import (
    CompanyOwner,
    CompanyPageResponse,
    CompanyResponse,
    MoneyResponse,
)
from common.pagination import Page


def to_company_response(details: CompanyDetails) -> CompanyResponse:
    company = details.company
    return CompanyResponse(
        id=str(company.id),
        name=company.name,
        domain=company.domain,
        industry=company.industry,
        size_range=COMPANY_SIZE_WIRE[company.size_range] if company.size_range else None,
        owner=CompanyOwner(id=str(company.owner_id), name=details.owner_name),
        visibility=VISIBILITY_WIRE[company.visibility],
        team_id=str(company.team_id) if company.team_id else None,
        people_count=details.people_count,
        open_deal_count=details.open_deal_count,
        open_value=[MoneyResponse(m.currency, f"{m.amount:.2f}") for m in details.open_value],
        created_at=company.created_at.isoformat(),
        updated_at=company.updated_at.isoformat(),
    )


def to_company_page_response(
    page: Page[CompanyDetails], next_link: str | None, previous_link: str | None
) -> CompanyPageResponse:
    return CompanyPageResponse(
        count=page.count,
        next=next_link,
        previous=previous_link,
        results=[to_company_response(item) for item in page.results],
    )
