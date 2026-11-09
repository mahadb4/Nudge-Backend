"""Base class for every endpoint that works inside one organization.

It runs after authentication, builds the TenantContext from the verified user and the
X-Organization-ID header (membership and role are read from the database), and refuses callers
whose role is not in allowed_roles before the endpoint reads anything else. Lives in config/ with
the other composition-root code because it reaches the services.
"""

from typing import ClassVar

from rest_framework.request import Request
from rest_framework.views import APIView

from common.constants import MetaKey, Role
from common.permissions import require_role
from common.tenancy import TenantContext
from config import container
from config.authentication import principal_of


class TenantApi(APIView):
    # None = any active member. Owner/Admin endpoints set (Role.OWNER, Role.ADMIN).
    allowed_roles: ClassVar[tuple[Role, ...] | None] = None

    def initial(self, request: Request, *args: object, **kwargs: object) -> None:
        super().initial(request, *args, **kwargs)
        context = container.tenant_service().resolve(
            user_id=principal_of(request).user_id,
            organization_header=request.META.get(MetaKey.ORGANIZATION),
        )
        if self.allowed_roles is not None:
            require_role(context, self.allowed_roles)
        request.tenant = context  # type: ignore[attr-defined]


def tenant_of(request: Request) -> TenantContext:
    """The TenantContext built by TenantApi.initial()."""
    return request.tenant  # type: ignore[attr-defined,no-any-return]
