"""Business objects of crm. Frozen dataclasses, no framework."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from apps.crm.domain.enums import CompanySize, ContactSource, StageOutcome, Visibility


@dataclass(frozen=True, slots=True)
class DealStage:
    id: UUID
    organization_id: UUID
    name: str
    position: int
    outcome: StageOutcome


@dataclass(frozen=True, slots=True)
class StageSummary:
    """A stage with the number of live deals in it (what the pipeline screens need)."""

    stage: DealStage
    deal_count: int


@dataclass(frozen=True, slots=True)
class Company:
    id: UUID
    organization_id: UUID
    owner_id: UUID
    team_id: UUID | None
    visibility: Visibility
    name: str
    domain: str | None
    industry: str | None
    size_range: CompanySize | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class MoneyTotal:
    currency: str
    amount: Decimal


@dataclass(frozen=True, slots=True)
class CompanyDetails:
    """A company with what the list and detail screens show next to it."""

    company: Company
    owner_name: str
    people_count: int
    open_deal_count: int
    open_value: tuple[MoneyTotal, ...]


@dataclass(frozen=True, slots=True)
class Contact:
    id: UUID
    organization_id: UUID
    company_id: UUID | None
    owner_id: UUID
    team_id: UUID | None
    visibility: Visibility
    first_name: str
    last_name: str | None
    email: str | None
    phone: str | None
    job_title: str | None
    source: ContactSource
    opted_out_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip() if self.last_name else self.first_name


@dataclass(frozen=True, slots=True)
class ContactDetails:
    """A contact with the names of its owner and (visible) company."""

    contact: Contact
    owner_name: str
    company_name: str | None
