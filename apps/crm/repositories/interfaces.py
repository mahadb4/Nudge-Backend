"""What the crm services need from storage. Every method takes the TenantContext first."""

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Protocol
from uuid import UUID

from apps.crm.domain.entities import (
    Company,
    CompanyDetails,
    Contact,
    ContactDetails,
    DealStage,
    StageSummary,
)
from apps.crm.domain.enums import StageOutcome
from common.pagination import ListQuery, Page
from common.tenancy import TenantContext


class StageRepository(Protocol):
    def count(self, context: TenantContext) -> int: ...

    def list_all(self, context: TenantContext) -> list[DealStage]:
        """Ordered by position. At most 12 stages exist, so this list is not paginated."""
        ...

    def list_with_counts(self, context: TenantContext) -> list[StageSummary]:
        """The same list with the number of live deals in each stage (two queries in total)."""
        ...

    def lock_all(self, context: TenantContext) -> list[DealStage]:
        """Every stage, ordered, locked until the transaction ends (call inside atomic())."""
        ...

    def create(
        self,
        context: TenantContext,
        *,
        stage_id: UUID,
        name: str,
        position: int,
        outcome: StageOutcome,
    ) -> DealStage:
        """Raises DuplicateStageName when the name exists already (ignoring case)."""
        ...

    def rename(self, context: TenantContext, stage_id: UUID, name: str) -> None:
        """Raises DuplicateStageName when another stage has the name (ignoring case)."""
        ...

    def set_positions(self, context: TenantContext, ordered_ids: Sequence[UUID]) -> None:
        """Positions become 0..n-1 in the given order."""
        ...

    def delete(self, context: TenantContext, stage_id: UUID) -> bool: ...

    def count_deals(self, context: TenantContext, stage_id: UUID) -> int:
        """All deals that point at the stage, soft-deleted ones included."""
        ...


class CompanyRepository(Protocol):
    def list_page(self, context: TenantContext, query: ListQuery) -> Page[CompanyDetails]:
        """Only companies the caller may see. Five queries however many rows."""
        ...

    def get(
        self, context: TenantContext, company_id: UUID, *, visible_only: bool = True
    ) -> CompanyDetails | None: ...

    def name_taken(self, context: TenantContext, name: str, except_id: UUID | None) -> bool:
        """Among live companies, ignoring case."""
        ...

    def domain_taken(self, context: TenantContext, domain: str, except_id: UUID | None) -> bool: ...

    def is_active_member(self, context: TenantContext, user_id: UUID) -> bool: ...

    def team_exists(self, context: TenantContext, team_id: UUID) -> bool: ...

    def is_in_team(self, context: TenantContext, team_id: UUID) -> bool: ...

    def lock_names(self, context: TenantContext) -> None:
        """Take the organization's company-name lock until the transaction ends."""
        ...

    def create(
        self, context: TenantContext, company_id: UUID, values: Mapping[str, object]
    ) -> Company:
        """Raises DuplicateCompanyDomain."""
        ...

    def update(
        self,
        context: TenantContext,
        company_id: UUID,
        expected_updated_at: datetime,
        changes: Mapping[str, object],
        now: datetime,
    ) -> bool:
        """False when updated_at is no longer expected_updated_at. Raises DuplicateCompanyDomain."""
        ...

    def soft_delete(self, context: TenantContext, company_id: UUID, now: datetime) -> bool: ...


class LinkRepository(Protocol):
    """The three questions companies and contacts both ask about owners and teams."""

    def is_active_member(self, context: TenantContext, user_id: UUID) -> bool: ...

    def team_exists(self, context: TenantContext, team_id: UUID) -> bool: ...

    def is_in_team(self, context: TenantContext, team_id: UUID) -> bool: ...


class ContactRepository(LinkRepository, Protocol):
    def list_page(self, context: TenantContext, query: ListQuery) -> Page[ContactDetails]:
        """Only contacts the caller may see. Four queries however many rows."""
        ...

    def get(
        self, context: TenantContext, contact_id: UUID, *, visible_only: bool = True
    ) -> ContactDetails | None: ...

    def find_by_email(
        self, context: TenantContext, email: str, except_id: UUID | None
    ) -> Contact | None:
        """The live contact using this email, whoever may see it."""
        ...

    def company_is_visible(self, context: TenantContext, company_id: UUID) -> bool: ...

    def create(
        self, context: TenantContext, contact_id: UUID, values: Mapping[str, object]
    ) -> Contact:
        """Raises DuplicateContactEmail."""
        ...

    def update(
        self,
        context: TenantContext,
        contact_id: UUID,
        expected_updated_at: datetime,
        changes: Mapping[str, object],
        now: datetime,
    ) -> bool:
        """False when updated_at is no longer expected_updated_at. Raises DuplicateContactEmail."""
        ...

    def soft_delete(self, context: TenantContext, contact_id: UUID, now: datetime) -> bool: ...
