"""Organizations table (the tenant root)."""

from collections.abc import Mapping
from uuid import UUID

from django.db.models.functions import Now

from apps.accounts.domain.entities import Organization
from apps.accounts.repositories.models import OrganizationModel
from common.constants import AccountType


def to_entity(row: OrganizationModel) -> Organization:
    return Organization(
        id=row.id,
        name=row.name,
        account_type=AccountType(row.account_type),
        timezone=row.timezone,
        created_at=row.created_at,
        automation_paused=row.automation_paused_at is not None,
    )


class PostgresOrganizationRepository:
    def get(self, organization_id: UUID) -> Organization | None:
        row = OrganizationModel.objects.filter(
            id=organization_id, deactivated_at__isnull=True
        ).first()
        return to_entity(row) if row else None

    def create(
        self, *, organization_id: UUID, name: str, account_type: AccountType, timezone: str
    ) -> Organization:
        row = OrganizationModel.objects.create(
            id=organization_id, name=name, account_type=int(account_type), timezone=timezone
        )
        return to_entity(row)

    def update_settings(
        self, organization_id: UUID, changes: Mapping[str, object]
    ) -> Organization | None:
        """changes may hold only name and timezone (what the settings page edits)."""
        columns = {name: changes[name] for name in ("name", "timezone") if name in changes}
        OrganizationModel.objects.filter(id=organization_id, deactivated_at__isnull=True).update(
            **columns, updated_at=Now()
        )
        return self.get(organization_id)

    def update_profile(
        self, *, organization_id: UUID, name: str, account_type: AccountType, timezone: str
    ) -> None:
        OrganizationModel.objects.filter(id=organization_id).update(
            name=name, account_type=int(account_type), timezone=timezone, updated_at=Now()
        )
