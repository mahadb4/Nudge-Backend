"""Builds (or tops up) the demo workspace through the real services, so every row is validated and
audited like a row made through the API.

Safe to run twice: the workspace is found by name, companies by name and contacts by email; what
already exists is left alone. The Owner's email and password are generated, shown once, and never
stored in code (only the password hash is stored, in the database).
"""

import secrets
from dataclasses import dataclass
from uuid import UUID

from apps.accounts.domain.entities import Organization
from apps.accounts.repositories.interfaces import (
    MembershipRepository,
    OrganizationRepository,
    UserRepository,
)
from apps.crm.domain.errors import ContactEmailTaken
from apps.crm.services.company_service import CompanyService
from apps.crm.services.contact_service import ContactService
from apps.crm.services.stage_service import StageService
from common.constants import AccountType, Limits, Role
from common.errors import Conflict
from common.interfaces import Clock, IdGenerator, PasswordHasher, UnitOfWork
from common.management.demo_data import (
    DEMO_COMPANIES,
    DEMO_CONTACTS,
    DEMO_EMAIL_DOMAIN,
    DEMO_ORGANIZATION,
    DEMO_OWNER_NAME,
    DEMO_TIMEZONE,
)
from common.pagination import ListQuery
from common.tenancy import TenantContext

PASSWORD_BYTES = 9
EMAIL_TAG_BYTES = 4


@dataclass(frozen=True, slots=True)
class DemoResult:
    organization_name: str
    owner_email: str
    password: str | None  # only when it was just created or reset
    created: bool
    stages: int
    companies: int
    contacts: int


def new_password() -> str:
    """Random, and always has a lower case letter, an upper case letter and a digit."""
    return f"{secrets.token_urlsafe(PASSWORD_BYTES)}Aa1"


def new_email() -> str:
    return f"demo-{secrets.token_hex(EMAIL_TAG_BYTES)}@{DEMO_EMAIL_DOMAIN}"


class DemoSeeder:
    def __init__(
        self,
        *,
        users: UserRepository,
        organizations: OrganizationRepository,
        memberships: MembershipRepository,
        stages: StageService,
        companies: CompanyService,
        contacts: ContactService,
        hasher: PasswordHasher,
        ids: IdGenerator,
        clock: Clock,
        uow: UnitOfWork,
    ) -> None:
        self._users = users
        self._organizations = organizations
        self._memberships = memberships
        self._stages = stages
        self._companies = companies
        self._contacts = contacts
        self._hasher = hasher
        self._ids = ids
        self._clock = clock
        self._uow = uow

    def run(self, *, reset_password: bool = False) -> DemoResult:
        with self._uow.atomic():
            organization = self._organizations.get_by_name(DEMO_ORGANIZATION)
            password: str | None = None
            created = organization is None
            if organization is None:
                organization, owner_id, password = self._create_workspace()
            else:
                owner_id = self._memberships.find_owner_user_id(organization.id)
                if owner_id is None:
                    raise LookupError("the demo workspace has no active Owner")
                if reset_password:
                    password = new_password()
                    self._users.set_password(owner_id, self._hasher.hash(password))
            owner = self._users.get(owner_id)
            if owner is None:
                raise LookupError("the demo Owner disappeared")
            context = TenantContext(owner_id, organization.id, Role.OWNER)
            stage_count = len(self._stages.seed_defaults(context))
            company_ids = self._seed_companies(context)
            self._seed_contacts(context, company_ids)
            return DemoResult(
                organization_name=organization.name,
                owner_email=owner.email,
                password=password,
                created=created,
                stages=stage_count,
                companies=self._companies.list_companies(context, _everything()).count,
                contacts=self._contacts.list_contacts(context, _everything()).count,
            )

    def _create_workspace(self) -> tuple[Organization, UUID, str]:
        password = new_password()
        user = self._users.create(
            user_id=self._ids.new_id(),
            email=new_email(),
            password_hash=self._hasher.hash(password),
            full_name=DEMO_OWNER_NAME,
            timezone=DEMO_TIMEZONE,
        )
        self._users.mark_email_verified(user.id, self._clock.now())
        organization = self._organizations.create(
            organization_id=self._ids.new_id(),
            name=DEMO_ORGANIZATION,
            account_type=AccountType.BUSINESS,
            timezone=DEMO_TIMEZONE,
        )
        self._memberships.create(
            membership_id=self._ids.new_id(),
            organization_id=organization.id,
            user_id=user.id,
            role=Role.OWNER,
        )
        return organization, user.id, password

    def _seed_companies(self, context: TenantContext) -> list[UUID]:
        for name, domain, industry, size in DEMO_COMPANIES:
            try:
                self._companies.create(
                    context,
                    {"name": name, "domain": domain, "industry": industry, "size_range": size},
                    None,
                )
            except Conflict:
                pass  # already there: leave it as it is
        by_name = {
            item.company.name: item.company.id
            for item in self._companies.list_companies(context, _everything()).results
        }
        return [by_name[name] for name, *_ in DEMO_COMPANIES]

    def _seed_contacts(self, context: TenantContext, company_ids: list[UUID]) -> None:
        for first, last, title, phone, company_index in DEMO_CONTACTS:
            body: dict[str, object] = {
                "first_name": first,
                "last_name": last,
                "email": f"{first}.{last}@{DEMO_EMAIL_DOMAIN}".lower(),
                "title": title,
                "phone": phone,
            }
            if company_index is not None:
                body["company_id"] = str(company_ids[company_index])
            try:
                self._contacts.create(context, body, None)
            except ContactEmailTaken:
                pass  # already there


def _everything() -> ListQuery:
    return ListQuery(page=1, page_size=Limits.PAGE_SIZE_MAX, q=None, ordering="name")
