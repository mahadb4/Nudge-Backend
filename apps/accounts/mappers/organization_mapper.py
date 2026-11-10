"""Organization entity -> response DTO."""

from apps.accounts.domain.entities import Organization
from apps.accounts.dtos.organization_dtos import OrganizationResponse
from common.constants import ACCOUNT_TYPE_WIRE


def to_organization_response(organization: Organization) -> OrganizationResponse:
    return OrganizationResponse(
        id=str(organization.id),
        name=organization.name,
        type=ACCOUNT_TYPE_WIRE[organization.account_type],
        timezone=organization.timezone,
        automation_paused=organization.automation_paused,
    )
