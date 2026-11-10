"""What accounts needs from other modules. Owned here (by the user of the service); crm implements
it."""

from collections.abc import Sequence
from typing import Protocol

from common.tenancy import TenantContext


class DefaultStageSeeder(Protocol):
    def seed_defaults(self, context: TenantContext) -> Sequence[object]:
        """Give a new organization its default deal stages. Safe to call twice."""
        ...
