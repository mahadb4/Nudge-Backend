"""What companies and contacts share: who counts as an active member, which teams exist and which
the caller belongs to, and the visibility rule. Owner and Admin see every live row; everyone else
sees organization-wide rows, their own rows and rows of their teams."""

from typing import TypeVar
from uuid import UUID

from django.db.models import Model, Q, QuerySet

from apps.crm.domain.enums import Visibility
from apps.crm.repositories.models import MemberModel, TeamMemberModel, TeamModel
from common.permissions import OWNER_OR_ADMIN
from common.tenancy import TenantContext

ACTIVE_MEMBER = 1
M = TypeVar("M", bound=Model)


def my_membership_ids(context: TenantContext) -> QuerySet[MemberModel]:
    return MemberModel.objects.filter(
        organization_id=context.organization_id, user_id=context.user_id, status=ACTIVE_MEMBER
    ).values("id")


def restrict_to_visible(rows: QuerySet[M], context: TenantContext) -> QuerySet[M]:
    """Apply the visibility rule to live rows of a table that has visibility, owner_id, team_id."""
    if context.role in OWNER_OR_ADMIN:
        return rows
    my_teams = TeamMemberModel.objects.filter(
        organization_id=context.organization_id, membership_id__in=my_membership_ids(context)
    ).values("team_id")
    return rows.filter(
        Q(visibility=Visibility.ORGANIZATION)
        | Q(owner_id=context.user_id)
        | Q(visibility=Visibility.TEAM, team_id__in=my_teams)
    )


class LinkRepository:
    """Mixed into the company and contact repositories (the same three questions for both)."""

    def is_active_member(self, context: TenantContext, user_id: UUID) -> bool:
        return MemberModel.objects.filter(
            organization_id=context.organization_id, user_id=user_id, status=ACTIVE_MEMBER
        ).exists()

    def team_exists(self, context: TenantContext, team_id: UUID) -> bool:
        return TeamModel.objects.filter(
            organization_id=context.organization_id, id=team_id
        ).exists()

    def is_in_team(self, context: TenantContext, team_id: UUID) -> bool:
        return TeamMemberModel.objects.filter(
            organization_id=context.organization_id,
            team_id=team_id,
            membership_id__in=my_membership_ids(context),
        ).exists()
