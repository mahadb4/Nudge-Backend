"""contacts table. Tenant-scoped and visibility-aware, like companies. A list or detail loads the
owner names and company names with ONE extra query each (no per-row queries)."""

from collections.abc import Mapping
from datetime import datetime
from uuid import UUID

from django.db import IntegrityError, transaction
from django.db.models import Q, QuerySet
from django.db.models.functions import Lower

from apps.crm.domain.entities import Contact, ContactDetails
from apps.crm.domain.enums import ContactSource, Visibility
from apps.crm.domain.errors import DuplicateContactEmail
from apps.crm.repositories.company_repository import PostgresCompanyRepository
from apps.crm.repositories.link_repository import LinkRepository, restrict_to_visible
from apps.crm.repositories.models import CompanyModel, ContactModel, PersonModel
from common.pagination import ListQuery, Page
from common.tenancy import TenantContext
from common.tenant_repository import TenantRepository

UNIQUE_EMAIL_INDEX = "uq_contacts_1"
# Public ordering name -> columns (the name order uses ix_contacts_2; no last name sorts last).
ORDERINGS = {
    "name": (Lower("last_name"), Lower("first_name"), "id"),
    "-created_at": ("-created_at", "-id"),
}
COLUMNS = (
    "first_name",
    "last_name",
    "email",
    "phone",
    "job_title",
    "company_id",
    "owner_id",
    "visibility",
    "team_id",
)


def _to_entity(row: ContactModel) -> Contact:
    return Contact(
        id=row.id,
        organization_id=row.organization_id,
        company_id=row.company_id,
        owner_id=row.owner_id,
        team_id=row.team_id,
        visibility=Visibility(row.visibility),
        first_name=row.first_name,
        last_name=row.last_name,
        email=row.email,
        phone=row.phone,
        job_title=row.job_title,
        source=ContactSource(row.source),
        opted_out_at=row.opted_out_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _is_duplicate_email(error: IntegrityError) -> bool:
    diag = getattr(error.__cause__, "diag", None)
    return getattr(diag, "constraint_name", None) == UNIQUE_EMAIL_INDEX


def _columns(values: Mapping[str, object]) -> dict[str, object]:
    columns = {name: values[name] for name in COLUMNS if name in values}
    if "visibility" in columns:
        columns["visibility"] = int(columns["visibility"])  # type: ignore[call-overload]
    return columns


def _search(
    rows: QuerySet[ContactModel], context: TenantContext, query: ListQuery
) -> QuerySet[ContactModel]:
    if query.q:
        company_ids = CompanyModel.objects.filter(
            organization_id=context.organization_id, name__icontains=query.q
        ).values("id")
        rows = rows.filter(
            Q(first_name__icontains=query.q)
            | Q(last_name__icontains=query.q)
            | Q(email__icontains=query.q)
            | Q(company_id__in=company_ids)
        )
    if "owner_id" in query.filters:
        rows = rows.filter(owner_id=query.filters["owner_id"])
    if "company_id" in query.filters:
        rows = rows.filter(company_id=query.filters["company_id"])
    if "status" in query.filters:
        opted_out = query.filters["status"]
        rows = rows.filter(opted_out_at__isnull=not opted_out)
    return rows


class PostgresContactRepository(LinkRepository, TenantRepository[ContactModel]):
    model = ContactModel

    # ---- reads

    def list_page(self, context: TenantContext, query: ListQuery) -> Page[ContactDetails]:
        """One page plus its total: count, page, owner names, company names (four queries)."""
        rows = _search(self._visible(context), context, query)
        count = rows.count()
        page = list(rows.order_by(*ORDERINGS[query.ordering])[query.offset :][: query.page_size])
        return Page(self._details(context, page), count, query)

    def get(
        self, context: TenantContext, contact_id: UUID, *, visible_only: bool = True
    ) -> ContactDetails | None:
        rows = self._visible(context) if visible_only else self._live(context)
        row = rows.filter(id=contact_id).first()
        return self._details(context, [row])[0] if row else None

    def find_by_email(
        self, context: TenantContext, email: str, except_id: UUID | None
    ) -> Contact | None:
        """The live contact using this email, whoever may see it."""
        rows = self._live(context).filter(email=email)
        row = (rows.exclude(id=except_id) if except_id else rows).first()
        return _to_entity(row) if row else None

    def company_is_visible(self, context: TenantContext, company_id: UUID) -> bool:
        return PostgresCompanyRepository().visible_rows(context).filter(id=company_id).exists()

    # ---- writes (call inside one transaction)

    def create(
        self, context: TenantContext, contact_id: UUID, values: Mapping[str, object]
    ) -> Contact:
        try:
            with transaction.atomic():  # a savepoint: a duplicate does not poison the caller
                row = ContactModel.objects.create(
                    id=contact_id,
                    organization_id=context.organization_id,
                    source=int(ContactSource.MANUAL),
                    **_columns(values),
                )
        except IntegrityError as exc:
            if _is_duplicate_email(exc):
                raise DuplicateContactEmail() from exc
            raise
        return _to_entity(row)

    def update(
        self,
        context: TenantContext,
        contact_id: UUID,
        expected_updated_at: datetime,
        changes: Mapping[str, object],
        now: datetime,
    ) -> bool:
        """Only applies if updated_at is still what the caller read; False otherwise."""
        try:
            with transaction.atomic():
                changed = (
                    self._live(context)
                    .filter(id=contact_id, updated_at=expected_updated_at)
                    .update(**_columns(changes), updated_at=now)
                )
        except IntegrityError as exc:
            if _is_duplicate_email(exc):
                raise DuplicateContactEmail() from exc
            raise
        return changed == 1

    def soft_delete(self, context: TenantContext, contact_id: UUID, now: datetime) -> bool:
        return self._live(context).filter(id=contact_id).update(deleted_at=now, updated_at=now) == 1

    # ---- helpers

    def _live(self, context: TenantContext) -> QuerySet[ContactModel]:
        return self._rows(context).filter(deleted_at__isnull=True)

    def _visible(self, context: TenantContext) -> QuerySet[ContactModel]:
        return restrict_to_visible(self._live(context), context)

    def _details(self, context: TenantContext, rows: list[ContactModel]) -> list[ContactDetails]:
        owners = dict(
            PersonModel.objects.filter(id__in={row.owner_id for row in rows}).values_list(
                "id", "full_name"
            )
        )
        # Only companies the caller may see are named; a private company stays private.
        company_ids = {row.company_id for row in rows if row.company_id}
        companies = dict(
            PostgresCompanyRepository()
            .visible_rows(context)
            .filter(id__in=company_ids)
            .values_list("id", "name")
        )
        return [
            ContactDetails(
                contact=_to_entity(row),
                owner_name=owners.get(row.owner_id, ""),
                company_name=companies.get(row.company_id) if row.company_id else None,
            )
            for row in rows
        ]
