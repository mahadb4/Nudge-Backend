"""Memberships table: who belongs to which organization, with which role."""

from uuid import UUID

from apps.accounts.domain.entities import Membership, MembershipWithOrganization
from apps.accounts.domain.enums import MembershipStatus
from apps.accounts.repositories.models import MembershipModel, OrganizationModel
from apps.accounts.repositories.organization_repository import to_entity as organization_entity
from common.constants import Role


def _to_entity(row: MembershipModel) -> Membership:
    return Membership(
        id=row.id,
        organization_id=row.organization_id,
        user_id=row.user_id,
        role=Role(row.role),
        status=MembershipStatus(row.status),
    )


class PostgresMembershipRepository:
    def create(
        self, *, membership_id: UUID, organization_id: UUID, user_id: UUID, role: Role
    ) -> Membership:
        row = MembershipModel.objects.create(
            id=membership_id,
            organization_id=organization_id,
            user_id=user_id,
            role=int(role),
            status=int(MembershipStatus.ACTIVE),
        )
        return _to_entity(row)

    def get_active(self, organization_id: UUID, user_id: UUID) -> Membership | None:
        # Both ids in the filter: asking for another organization's membership finds nothing (tenant
        # check).
        row = MembershipModel.objects.filter(
            organization_id=organization_id, user_id=user_id, status=int(MembershipStatus.ACTIVE)
        ).first()
        return _to_entity(row) if row else None

    def list_active_for_user(self, user_id: UUID) -> list[MembershipWithOrganization]:
        memberships = list(
            MembershipModel.objects.filter(
                user_id=user_id, status=int(MembershipStatus.ACTIVE)
            ).order_by("created_at", "id")
        )
        # One more query for all organizations at once (not one per membership).
        organizations = {
            org.id: org
            for org in OrganizationModel.objects.filter(
                id__in=[m.organization_id for m in memberships], deactivated_at__isnull=True
            )
        }
        return [
            MembershipWithOrganization(
                _to_entity(m), organization_entity(organizations[m.organization_id])
            )
            for m in memberships
            if m.organization_id in organizations
        ]
