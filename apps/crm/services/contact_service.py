"""Contact use cases: list, read, create, update, soft delete. Same shape as companies: every write
is one transaction and one audit row; PATCH needs the updated_at the client read."""

from collections.abc import Mapping
from uuid import UUID

from apps.crm.domain.entities import Contact, ContactDetails
from apps.crm.domain.enums import VISIBILITY_WIRE, Visibility
from apps.crm.domain.errors import ContactEmailTaken, DuplicateContactEmail, StaleContact
from apps.crm.repositories.interfaces import ContactRepository
from apps.crm.services.contact_validator import ContactValidator
from apps.crm.services.link_service import LinkService
from common.constants import ActorType, AuditAction
from common.errors import FieldIssue, NotFound, ValidationFailed
from common.interfaces import AuditEvent, AuditWriter, Clock, IdGenerator, UnitOfWork
from common.messages import Messages
from common.pagination import ListQuery, Page
from common.tenancy import TenantContext

AUDIT_OBJECT_CONTACT = "contact"
# Personal data: the audit row says the field changed, never what it was or became.
PERSONAL = ("first_name", "last_name", "email", "phone", "job_title")


class ContactService:
    def __init__(
        self,
        contacts: ContactRepository,
        ids: IdGenerator,
        audit: AuditWriter,
        uow: UnitOfWork,
        validator: ContactValidator,
        clock: Clock,
        links: LinkService,
    ) -> None:
        self._contacts = contacts
        self._ids = ids
        self._audit = audit
        self._uow = uow
        self._validator = validator
        self._clock = clock
        self._links = links

    def list_contacts(self, context: TenantContext, query: ListQuery) -> Page[ContactDetails]:
        return self._contacts.list_page(context, query)

    def get_contact(self, context: TenantContext, contact_id: UUID) -> ContactDetails:
        found = self._contacts.get(context, contact_id)
        if found is None:
            raise NotFound()
        return found

    def create(
        self, context: TenantContext, sent: dict[str, object], ip_address: str | None
    ) -> ContactDetails:
        values = {
            "owner_id": context.user_id,
            "visibility": Visibility.ORGANIZATION,
            "team_id": None,
            "company_id": None,
            **self._validator.validate_create(sent),
        }
        contact_id = self._ids.new_id()
        with self._uow.atomic():
            self._check(context, values, owner_changed=True, team_changed=True)
            self._check_email(context, values, except_id=None)
            try:
                contact = self._contacts.create(context, contact_id, values)
            except DuplicateContactEmail:
                raise self._email_taken(context, str(values["email"]), None) from None
            self._record(context, AuditAction.CONTACT_CREATE, contact, {}, ip_address)
        return self._written(context, contact_id)

    def update(
        self,
        context: TenantContext,
        contact_id: UUID,
        sent: dict[str, object],
        ip_address: str | None,
    ) -> ContactDetails:
        expected_updated_at, changes = self._validator.validate_update(sent)
        with self._uow.atomic():
            current = self.get_contact(context, contact_id)
            if current.contact.updated_at != expected_updated_at:
                raise StaleContact(current)
            before = _values(current.contact)
            changes = _with_consistent_team(current.contact, changes)
            changed = {k: v for k, v in changes.items() if v != before[k]}
            if not changed:
                return current
            merged = {**before, **changed}
            self._check(
                context,
                merged,
                owner_changed="owner_id" in changed,
                team_changed="team_id" in changed or "visibility" in changed,
            )
            self._check_email(context, changed, except_id=contact_id)
            try:
                updated = self._contacts.update(
                    context, contact_id, expected_updated_at, changed, self._clock.now()
                )
            except DuplicateContactEmail:
                raise self._email_taken(context, str(changed["email"]), contact_id) from None
            if not updated:
                raise StaleContact(self.get_contact(context, contact_id))
            self._record(
                context,
                AuditAction.CONTACT_UPDATE,
                current.contact,
                {k: _change(k, before[k], v) for k, v in changed.items()},
                ip_address,
            )
        return self._written(context, contact_id)

    def delete(self, context: TenantContext, contact_id: UUID, ip_address: str | None) -> None:
        with self._uow.atomic():
            current = self.get_contact(context, contact_id)
            if not self._contacts.soft_delete(context, contact_id, self._clock.now()):
                raise NotFound()
            self._record(context, AuditAction.CONTACT_DELETE, current.contact, {}, ip_address)

    # ---- rules

    def _check(
        self,
        context: TenantContext,
        values: Mapping[str, object],
        *,
        owner_changed: bool,
        team_changed: bool,
    ) -> None:
        issues: dict[str, list[FieldIssue]] = {}
        company = values.get("company_id")
        if company is not None and not self._contacts.company_is_visible(context, company):  # type: ignore[arg-type]
            issues["company_id"] = [FieldIssue(Messages.VALIDATION_COMPANY_INVALID)]
        try:
            self._links.check(
                context,
                owner_id=values["owner_id"],  # type: ignore[arg-type]
                visibility=values["visibility"],  # type: ignore[arg-type]
                team_id=values["team_id"],  # type: ignore[arg-type]
                owner_changed=owner_changed,
                team_changed=team_changed,
            )
        except ValidationFailed as failed:
            issues.update({name: list(found) for name, found in failed.fields.items()})
        if issues:
            raise ValidationFailed.from_issues(issues)

    def _check_email(
        self, context: TenantContext, values: Mapping[str, object], *, except_id: UUID | None
    ) -> None:
        email = values.get("email")
        if isinstance(email, str) and self._contacts.find_by_email(context, email, except_id):
            raise self._email_taken(context, email, except_id)

    def _email_taken(
        self, context: TenantContext, email: str, except_id: UUID | None
    ) -> ContactEmailTaken:
        """The 409, naming the other contact only if the caller may see it."""
        other = self._contacts.find_by_email(context, email, except_id)
        visible = self._contacts.get(context, other.id) if other else None
        return ContactEmailTaken(visible)

    def _written(self, context: TenantContext, contact_id: UUID) -> ContactDetails:
        found = self._contacts.get(context, contact_id, visible_only=False)
        if found is None:
            raise NotFound()
        return found

    def _record(
        self,
        context: TenantContext,
        action: AuditAction,
        contact: Contact,
        changes: dict[str, object],
        ip_address: str | None,
    ) -> None:
        self._audit.write(
            AuditEvent(
                action=action,
                actor_type=ActorType.USER,
                actor_id=context.user_id,
                organization_id=context.organization_id,
                object_type=AUDIT_OBJECT_CONTACT,
                object_id=contact.id,
                details={"label": contact.full_name, "changes": changes},
                ip_address=ip_address,
            )
        )


def _values(contact: Contact) -> dict[str, object]:
    return {
        "first_name": contact.first_name,
        "last_name": contact.last_name,
        "email": contact.email,
        "phone": contact.phone,
        "job_title": contact.job_title,
        "company_id": contact.company_id,
        "owner_id": contact.owner_id,
        "visibility": contact.visibility,
        "team_id": contact.team_id,
    }


def _change(field: str, before: object, after: object) -> object:
    if field in PERSONAL:
        return "changed"
    return {"from": _plain(before), "to": _plain(after)}


def _plain(value: object) -> object:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Visibility):
        return VISIBILITY_WIRE[value]
    return value


def _with_consistent_team(contact: Contact, changes: dict[str, object]) -> dict[str, object]:
    """Leaving team visibility without naming a team drops the team."""
    result = dict(changes)
    new_visibility = result.get("visibility")
    if (
        new_visibility is not None
        and new_visibility is not Visibility.TEAM
        and "team_id" not in result
        and contact.team_id is not None
    ):
        result["team_id"] = None
    return result
