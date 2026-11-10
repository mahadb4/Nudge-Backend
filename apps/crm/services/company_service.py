"""Company use cases: list, read, create, update, soft delete. Every write runs in one transaction,
is audited, and keeps the rules the database cannot: unique name among live rows, owner is an
active member, team visibility needs one of the caller's teams."""

from collections.abc import Mapping
from uuid import UUID

from apps.crm.domain.entities import CompanyDetails
from apps.crm.domain.enums import COMPANY_SIZE_WIRE, VISIBILITY_WIRE, CompanySize, Visibility
from apps.crm.domain.errors import DuplicateCompanyDomain, StaleCompany
from apps.crm.repositories.interfaces import CompanyRepository
from apps.crm.services.company_validator import CompanyValidator
from apps.crm.services.link_service import LinkService
from common.constants import ActorType, AuditAction
from common.errors import Conflict, NotFound
from common.interfaces import AuditEvent, AuditWriter, Clock, IdGenerator, UnitOfWork
from common.messages import Messages
from common.pagination import ListQuery, Page
from common.tenancy import TenantContext

AUDIT_OBJECT_COMPANY = "company"
TRACKED = ("name", "domain", "industry", "size_range", "owner_id", "visibility", "team_id")


class CompanyService:
    def __init__(
        self,
        companies: CompanyRepository,
        ids: IdGenerator,
        audit: AuditWriter,
        uow: UnitOfWork,
        validator: CompanyValidator,
        clock: Clock,
        links: LinkService,
    ) -> None:
        self._companies = companies
        self._ids = ids
        self._audit = audit
        self._uow = uow
        self._validator = validator
        self._clock = clock
        self._links = links

    def list_companies(self, context: TenantContext, query: ListQuery) -> Page[CompanyDetails]:
        return self._companies.list_page(context, query)

    def get_company(self, context: TenantContext, company_id: UUID) -> CompanyDetails:
        found = self._companies.get(context, company_id)
        if found is None:
            raise NotFound()
        return found

    def create(
        self, context: TenantContext, sent: dict[str, object], ip_address: str | None
    ) -> CompanyDetails:
        values = {
            "owner_id": context.user_id,
            "visibility": Visibility.ORGANIZATION,
            "team_id": None,
            **self._validator.validate_create(sent),
        }
        company_id = self._ids.new_id()
        with self._uow.atomic():
            self._companies.lock_names(context)
            self._check_links(context, values, owner_changed=True, team_changed=True)
            self._check_unique(context, values, except_id=None)
            try:
                self._companies.create(context, company_id, values)
            except DuplicateCompanyDomain:
                raise Conflict(Messages.CRM_COMPANY_DOMAIN_TAKEN) from None
            self._record(
                context, AuditAction.COMPANY_CREATE, company_id, str(values["name"]), {}, ip_address
            )
        return self._written(context, company_id)

    def update(
        self,
        context: TenantContext,
        company_id: UUID,
        sent: dict[str, object],
        ip_address: str | None,
    ) -> CompanyDetails:
        expected_updated_at, changes = self._validator.validate_update(sent)
        with self._uow.atomic():
            self._companies.lock_names(context)
            current = self.get_company(context, company_id)
            if current.company.updated_at != expected_updated_at:
                raise StaleCompany(current)
            before = _snapshot(current)
            changes = _with_consistent_team(current, changes)
            changed = {k: v for k, v in changes.items() if _plain(v) != before[k]}
            if not changed:
                return current
            self._check_links(
                context,
                {**_current_values(current), **changed},
                owner_changed="owner_id" in changed,
                team_changed="team_id" in changed or "visibility" in changed,
            )
            self._check_unique(context, changed, except_id=company_id)
            try:
                updated = self._companies.update(
                    context, company_id, expected_updated_at, changed, self._clock.now()
                )
            except DuplicateCompanyDomain:
                raise Conflict(Messages.CRM_COMPANY_DOMAIN_TAKEN) from None
            if not updated:
                raise StaleCompany(self.get_company(context, company_id))
            self._record(
                context,
                AuditAction.COMPANY_UPDATE,
                company_id,
                current.company.name,
                {k: {"from": before[k], "to": _plain(v)} for k, v in changed.items()},
                ip_address,
            )
        return self._written(context, company_id)

    def delete(self, context: TenantContext, company_id: UUID, ip_address: str | None) -> None:
        with self._uow.atomic():
            current = self.get_company(context, company_id)
            if not self._companies.soft_delete(context, company_id, self._clock.now()):
                raise NotFound()
            self._record(
                context,
                AuditAction.COMPANY_DELETE,
                company_id,
                current.company.name,
                {},
                ip_address,
            )

    # ---- rules

    def _check_links(
        self,
        context: TenantContext,
        values: Mapping[str, object],
        *,
        owner_changed: bool,
        team_changed: bool,
    ) -> None:
        self._links.check(
            context,
            owner_id=values["owner_id"],  # type: ignore[arg-type]
            visibility=values["visibility"],  # type: ignore[arg-type]
            team_id=values["team_id"],  # type: ignore[arg-type]
            owner_changed=owner_changed,
            team_changed=team_changed,
        )

    def _check_unique(
        self, context: TenantContext, values: Mapping[str, object], *, except_id: UUID | None
    ) -> None:
        name = values.get("name")
        if isinstance(name, str) and self._companies.name_taken(context, name, except_id):
            raise Conflict(Messages.CRM_COMPANY_NAME_TAKEN)
        domain = values.get("domain")
        if isinstance(domain, str) and self._companies.domain_taken(context, domain, except_id):
            raise Conflict(Messages.CRM_COMPANY_DOMAIN_TAKEN)

    def _written(self, context: TenantContext, company_id: UUID) -> CompanyDetails:
        found = self._companies.get(context, company_id, visible_only=False)
        if found is None:
            raise NotFound()
        return found

    def _record(
        self,
        context: TenantContext,
        action: AuditAction,
        company_id: UUID,
        label: str,
        changes: dict[str, object],
        ip_address: str | None,
    ) -> None:
        self._audit.write(
            AuditEvent(
                action=action,
                actor_type=ActorType.USER,
                actor_id=context.user_id,
                organization_id=context.organization_id,
                object_type=AUDIT_OBJECT_COMPANY,
                object_id=company_id,
                details={"label": label, "changes": changes},
                ip_address=ip_address,
            )
        )


def _current_values(current: CompanyDetails) -> dict[str, object]:
    company = current.company
    return {
        "name": company.name,
        "domain": company.domain,
        "industry": company.industry,
        "size_range": company.size_range,
        "owner_id": company.owner_id,
        "visibility": company.visibility,
        "team_id": company.team_id,
    }


def _plain(value: object) -> object:
    """A JSON-friendly form for the audit details and for comparing before with after."""
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Visibility):
        return VISIBILITY_WIRE[value]
    if isinstance(value, CompanySize):
        return COMPANY_SIZE_WIRE[value]
    return value


def _snapshot(current: CompanyDetails) -> dict[str, object]:
    return {name: _plain(value) for name, value in _current_values(current).items()}


def _with_consistent_team(current: CompanyDetails, changes: dict[str, object]) -> dict[str, object]:
    """Leaving team visibility without naming a team drops the team."""
    result = dict(changes)
    new_visibility = result.get("visibility")
    if (
        new_visibility is not None
        and new_visibility is not Visibility.TEAM
        and "team_id" not in result
        and current.company.team_id is not None
    ):
        result["team_id"] = None
    return result
