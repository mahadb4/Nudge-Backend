"""The signed-in user with their organizations."""

from uuid import UUID

from apps.accounts.domain.entities import Me
from apps.accounts.repositories.interfaces import MembershipRepository, UserRepository
from apps.accounts.services.tenant_service import choose_membership
from common.errors import NotFound


class MeService:
    def __init__(self, users: UserRepository, memberships: MembershipRepository) -> None:
        self._users = users
        self._memberships = memberships

    def get_me(self, user_id: UUID, organization_header: str | None = None) -> Me:
        """current = the organization named by X-Organization-ID, else the oldest membership."""
        user = self._users.get(user_id)
        organizations = self._memberships.list_active_for_user(user_id)
        if user is None or not organizations:
            raise NotFound()
        current = choose_membership(organizations, organization_header, must_choose=False)
        return Me(user=user, current=current, organizations=tuple(organizations))
