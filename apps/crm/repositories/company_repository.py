"""companies table. Tenant-scoped (TenantRepository) and visibility-aware: Owner and Admin see every
live row, everyone else sees organization-wide rows, their own rows and their teams' rows."""

from collections import defaultdict
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from django.db import IntegrityError, connection, transaction
from django.db.models import Count, Q, QuerySet, Sum
from django.db.models.functions import Lower

from apps.crm.domain.entities import Company, CompanyDetails, MoneyTotal
from apps.crm.domain.enums import CompanySize, StageOutcome, Visibility
from apps.crm.domain.errors import DuplicateCompanyDomain
from apps.crm.repositories.link_repository import LinkRepository, restrict_to_visible
from apps.crm.repositories.models import (
    CompanyModel,
    ContactModel,
    DealModel,
    DealStageModel,
    PersonModel,
)
from common.pagination import ListQuery, Page
from common.tenancy import TenantContext
from common.tenant_repository import TenantRepository

UNIQUE_DOMAIN_INDEX = "uq_companies_1"
# Public ordering name -> the columns to sort by (the name order uses ix_companies_2).
ORDERINGS = {
    "name": (Lower("name"), "id"),
    "-created_at": ("-created_at", "-id"),
}
COLUMNS = (
    "name",
    "domain",
    "industry",
    "size_range",
    "owner_id",
    "visibility",
    "team_id",
)


def _to_entity(row: CompanyModel) -> Company:
    return Company(
        id=row.id,
        organization_id=row.organization_id,
        owner_id=row.owner_id,
        team_id=row.team_id,
        visibility=Visibility(row.visibility),
        name=row.name,
        domain=row.domain,
        industry=row.industry,
        size_range=CompanySize(row.size_range) if row.size_range else None,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _is_duplicate_domain(error: IntegrityError) -> bool:
    diag = getattr(error.__cause__, "diag", None)
    return getattr(diag, "constraint_name", None) == UNIQUE_DOMAIN_INDEX


def _columns(values: Mapping[str, object]) -> dict[str, object]:
    columns = {name: values[name] for name in COLUMNS if name in values}
    if "visibility" in columns:
        columns["visibility"] = int(columns["visibility"])  # type: ignore[call-overload]
    if columns.get("size_range") is not None:
        columns["size_range"] = int(columns["size_range"])  # type: ignore[call-overload]
    return columns


def _search(rows: QuerySet[CompanyModel], query: ListQuery) -> QuerySet[CompanyModel]:
    if query.q:
        rows = rows.filter(
            Q(name__icontains=query.q)
            | Q(domain__icontains=query.q)
            | Q(industry__icontains=query.q)
        )
    owner = query.filters.get("owner_id")
    return rows.filter(owner_id=owner) if owner else rows


class PostgresCompanyRepository(LinkRepository, TenantRepository[CompanyModel]):
    model = CompanyModel

    # ---- reads

    def list_page(self, context: TenantContext, query: ListQuery) -> Page[CompanyDetails]:
        """One page plus its total. Five queries however many rows: count, page, owners, people,
        open deals."""
        rows = _search(self._visible(context), query)
        count = rows.count()
        page = list(rows.order_by(*ORDERINGS[query.ordering])[query.offset :][: query.page_size])
        return Page(self._details(context, page), count, query)

    def get(
        self, context: TenantContext, company_id: UUID, *, visible_only: bool = True
    ) -> CompanyDetails | None:
        """A live company. visible_only=False skips the visibility rule: for the reply to a write
        (someone may create a private company for a colleague)."""
        rows = self._visible(context) if visible_only else self._live(context)
        row = rows.filter(id=company_id).first()
        return self._details(context, [row])[0] if row else None

    def name_taken(self, context: TenantContext, name: str, except_id: UUID | None) -> bool:
        rows = self._live(context).annotate(lowered=Lower("name")).filter(lowered=name.lower())
        return (rows.exclude(id=except_id) if except_id else rows).exists()

    def domain_taken(self, context: TenantContext, domain: str, except_id: UUID | None) -> bool:
        rows = self._live(context).filter(domain=domain)
        return (rows.exclude(id=except_id) if except_id else rows).exists()

    # ---- writes (call inside one transaction)

    def lock_names(self, context: TenantContext) -> None:
        """Serialises company creates and renames of one organization, so the 'name is unique among
        live rows' check cannot race (the database only has a plain index for it)."""
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                [f"companies:{context.organization_id}"],
            )

    def create(
        self, context: TenantContext, company_id: UUID, values: Mapping[str, object]
    ) -> Company:
        try:
            with transaction.atomic():  # a savepoint: a duplicate does not poison the caller
                row = CompanyModel.objects.create(
                    id=company_id, organization_id=context.organization_id, **_columns(values)
                )
        except IntegrityError as exc:
            if _is_duplicate_domain(exc):
                raise DuplicateCompanyDomain() from exc
            raise
        return _to_entity(row)

    def update(
        self,
        context: TenantContext,
        company_id: UUID,
        expected_updated_at: datetime,
        changes: Mapping[str, object],
        now: datetime,
    ) -> bool:
        """The write only happens if updated_at is still what the caller read. False = it changed
        (or the row is gone), so the caller reports a conflict."""
        try:
            with transaction.atomic():
                changed = (
                    self._live(context)
                    .filter(id=company_id, updated_at=expected_updated_at)
                    .update(**_columns(changes), updated_at=now)
                )
        except IntegrityError as exc:
            if _is_duplicate_domain(exc):
                raise DuplicateCompanyDomain() from exc
            raise
        return changed == 1

    def soft_delete(self, context: TenantContext, company_id: UUID, now: datetime) -> bool:
        return self._live(context).filter(id=company_id).update(deleted_at=now, updated_at=now) == 1

    # ---- helpers

    def _live(self, context: TenantContext) -> QuerySet[CompanyModel]:
        return self._rows(context).filter(deleted_at__isnull=True)

    def visible_rows(self, context: TenantContext) -> QuerySet[CompanyModel]:
        """Live companies the caller may see (also used by the contact repository)."""
        return restrict_to_visible(self._live(context), context)

    def _visible(self, context: TenantContext) -> QuerySet[CompanyModel]:
        return self.visible_rows(context)

    def _details(self, context: TenantContext, rows: list[CompanyModel]) -> list[CompanyDetails]:
        """Owner names, people counts and open-deal totals for the given companies, each in ONE
        query for all of them (no per-company queries)."""
        ids = [row.id for row in rows]
        owners = dict(
            PersonModel.objects.filter(id__in={row.owner_id for row in rows}).values_list(
                "id", "full_name"
            )
        )
        people = dict(
            ContactModel.objects.filter(
                organization_id=context.organization_id, company_id__in=ids, deleted_at__isnull=True
            )
            .values_list("company_id")
            .annotate(total=Count("id"))
        )
        open_stages = DealStageModel.objects.filter(
            organization_id=context.organization_id, outcome=int(StageOutcome.OPEN)
        ).values("id")
        deals: dict[UUID, list[MoneyTotal]] = defaultdict(list)
        counts: dict[UUID, int] = defaultdict(int)
        grouped = (
            DealModel.objects.filter(
                organization_id=context.organization_id,
                company_id__in=ids,
                deleted_at__isnull=True,
                stage_id__in=open_stages,
            )
            .values_list("company_id", "currency")
            .annotate(total=Count("id"), money=Sum("amount"))
            .order_by("company_id", "currency")
        )
        for company_id, currency, total, money in grouped:
            counts[company_id] += total
            deals[company_id].append(MoneyTotal(currency, money or Decimal("0.00")))
        return [
            CompanyDetails(
                company=_to_entity(row),
                owner_name=owners.get(row.owner_id, ""),
                people_count=people.get(row.id, 0),
                open_deal_count=counts.get(row.id, 0),
                open_value=tuple(deals.get(row.id, ())),
            )
            for row in rows
        ]
