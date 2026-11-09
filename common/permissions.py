"""Role checks. The role always comes from the database membership (TenantContext), so a role
change takes effect on the very next request."""

from collections.abc import Collection

from common.constants import Role
from common.errors import Forbidden
from common.tenancy import TenantContext

OWNER_OR_ADMIN: tuple[Role, ...] = (Role.OWNER, Role.ADMIN)


def require_role(context: TenantContext, allowed: Collection[Role]) -> None:
    """Raises Forbidden (403) unless the caller's role is one of the allowed roles."""
    if context.role not in allowed:
        raise Forbidden()
