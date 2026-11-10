"""The owner and team rules companies and contacts share: the owner is an active member, team
visibility has one of the caller's teams (Owner and Admin may use any team), other visibilities have
no team."""

from uuid import UUID

from apps.crm.domain.enums import Visibility
from apps.crm.repositories.interfaces import LinkRepository
from common.errors import FieldIssue, ValidationFailed
from common.messages import Messages
from common.permissions import OWNER_OR_ADMIN
from common.tenancy import TenantContext


class LinkService:
    def __init__(self, links: LinkRepository) -> None:
        self._links = links

    def check(
        self,
        context: TenantContext,
        *,
        owner_id: UUID,
        visibility: Visibility,
        team_id: UUID | None,
        owner_changed: bool,
        team_changed: bool,
    ) -> None:
        """Raises one ValidationFailed listing every broken link."""
        issues: dict[str, list[FieldIssue]] = {}
        if owner_changed and not self._links.is_active_member(context, owner_id):
            issues["owner_id"] = [FieldIssue(Messages.VALIDATION_MEMBER_INVALID)]
        if visibility is Visibility.TEAM and team_id is None:
            issues["team_id"] = [FieldIssue(Messages.VALIDATION_TEAM_REQUIRED)]
        elif visibility is not Visibility.TEAM and team_id is not None:
            issues["team_id"] = [FieldIssue(Messages.VALIDATION_TEAM_NOT_ALLOWED)]
        elif team_changed and team_id is not None and not self._may_use_team(context, team_id):
            issues["team_id"] = [FieldIssue(Messages.VALIDATION_TEAM_INVALID)]
        if issues:
            raise ValidationFailed.from_issues(issues)

    def _may_use_team(self, context: TenantContext, team_id: UUID) -> bool:
        if not self._links.team_exists(context, team_id):
            return False
        return context.role in OWNER_OR_ADMIN or self._links.is_in_team(context, team_id)
