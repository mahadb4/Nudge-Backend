"""Who is asking and for which organization. Built once per request from the verified user, the
X-Organization-ID header and the database, never from anything the client claims about its role."""

from dataclasses import dataclass
from uuid import UUID

from common.constants import Role


@dataclass(frozen=True, slots=True)
class TenantContext:
    user_id: UUID
    organization_id: UUID
    role: Role
