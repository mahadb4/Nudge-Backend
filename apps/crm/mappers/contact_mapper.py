"""Contact entities -> response DTOs."""

from apps.crm.domain.entities import ContactDetails
from apps.crm.domain.enums import CONTACT_SOURCE_WIRE, VISIBILITY_WIRE
from apps.crm.dtos.contact_dtos import (
    ContactCompany,
    ContactOwner,
    ContactPageResponse,
    ContactResponse,
)
from common.pagination import Page

STATUS_ACTIVE = "active"
STATUS_OPTED_OUT = "opted_out"


def to_contact_response(details: ContactDetails) -> ContactResponse:
    contact = details.contact
    company = (
        ContactCompany(id=str(contact.company_id), name=details.company_name)
        if contact.company_id and details.company_name is not None
        else None
    )
    return ContactResponse(
        id=str(contact.id),
        first_name=contact.first_name,
        last_name=contact.last_name,
        name=contact.full_name,
        email=contact.email,
        phone=contact.phone,
        title=contact.job_title,
        company=company,
        owner=ContactOwner(id=str(contact.owner_id), name=details.owner_name),
        visibility=VISIBILITY_WIRE[contact.visibility],
        team_id=str(contact.team_id) if contact.team_id else None,
        status=STATUS_OPTED_OUT if contact.opted_out_at else STATUS_ACTIVE,
        opted_out_at=contact.opted_out_at.isoformat() if contact.opted_out_at else None,
        source=CONTACT_SOURCE_WIRE[contact.source],
        last_contact_at=None,  # no mail exists yet
        created_at=contact.created_at.isoformat(),
        updated_at=contact.updated_at.isoformat(),
    )


def to_contact_page_response(
    page: Page[ContactDetails], next_link: str | None, previous_link: str | None
) -> ContactPageResponse:
    return ContactPageResponse(
        count=page.count,
        next=next_link,
        previous=previous_link,
        results=[to_contact_response(item) for item in page.results],
    )
