"""Which organization a request is about, and what role the caller has there. Always read from the
memberships table on every request, so a removed or demoted member is stopped at once."""

import re
from collections.abc import Sequence
from uuid import UUID

from apps.accounts.domain.entities import MembershipWithOrganization
from apps.accounts.repositories.interfaces import MembershipRepository
from common.errors import NotFound, ValidationFailed
from common.messages import Messages
from common.tenancy import TenantContext

_UUID_TEXT = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


def choose_membership(
    memberships: Sequence[MembershipWithOrganization], requested: str | None, *, must_choose: bool
) -> MembershipWithOrganization:
    """The membership a request is about.

    requested is the X-Organization-ID header (None = not sent). A header naming an organization
    the user is not an active member of is 404, the same as one that does not exist.
    Without a header: the only membership; with several, either the oldest (must_choose False, for
    "who am I") or a 400 asking the client to choose.
    """
    if requested is not None:
        if not _UUID_TEXT.fullmatch(requested):
            raise NotFound()
        wanted = UUID(requested)
        found = next((m for m in memberships if m.organization.id == wanted), None)
        if found is None:
            raise NotFound()
        return found
    if not memberships:
        raise NotFound()
    if len(memberships) > 1 and must_choose:
        raise ValidationFailed(Messages.TENANCY_ORGANIZATION_REQUIRED)
    return memberships[0]


class TenantService:
    def __init__(self, memberships: MembershipRepository) -> None:
        self._memberships = memberships

    def resolve(self, *, user_id: UUID, organization_header: str | None) -> TenantContext:
        chosen = choose_membership(
            self._memberships.list_active_for_user(user_id), organization_header, must_choose=True
        )
        return TenantContext(
            user_id=user_id,
            organization_id=chosen.organization.id,
            role=chosen.membership.role,
        )
