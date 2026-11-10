"""The current organization: read it, and let an Owner or Admin edit its name and time zone."""

from apps.accounts.domain.entities import Organization
from apps.accounts.repositories.interfaces import OrganizationRepository
from apps.accounts.services.user_validator import UserValidator
from common.constants import ActorType, AuditAction
from common.errors import NotFound
from common.interfaces import AuditEvent, AuditWriter, UnitOfWork
from common.permissions import OWNER_OR_ADMIN, require_role
from common.tenancy import TenantContext

AUDIT_OBJECT_ORGANIZATION = "organization"


class OrganizationService:
    def __init__(
        self,
        *,
        validator: UserValidator,
        organizations: OrganizationRepository,
        audit: AuditWriter,
        uow: UnitOfWork,
    ) -> None:
        self._validator = validator
        self._organizations = organizations
        self._audit = audit
        self._uow = uow

    def get_current(self, context: TenantContext) -> Organization:
        organization = self._organizations.get(context.organization_id)
        if organization is None:
            raise NotFound()
        return organization

    def update_current(
        self, context: TenantContext, sent: dict[str, object], ip_address: str | None
    ) -> Organization:
        require_role(context, OWNER_OR_ADMIN)
        changes = self._validator.validate_organization_settings(sent)
        if not changes:
            return self.get_current(context)
        with self._uow.atomic():
            updated = self._organizations.update_settings(context.organization_id, changes)
            if updated is None:
                raise NotFound()
            self._audit.write(
                AuditEvent(
                    action=AuditAction.ORGANIZATION_UPDATE,
                    actor_type=ActorType.USER,
                    actor_id=context.user_id,
                    organization_id=context.organization_id,
                    object_type=AUDIT_OBJECT_ORGANIZATION,
                    object_id=context.organization_id,
                    details={"fields": sorted(changes)},
                    ip_address=ip_address,
                )
            )
        return updated
