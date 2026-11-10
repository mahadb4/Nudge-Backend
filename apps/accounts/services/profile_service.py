"""The signed-in user edits their own profile."""

from dataclasses import replace
from uuid import UUID

from apps.accounts.domain.entities import Me
from apps.accounts.repositories.interfaces import UserRepository
from apps.accounts.services.me_service import MeService
from apps.accounts.services.user_validator import UserValidator
from common.constants import ActorType, AuditAction
from common.errors import FieldIssue, NotFound, ValidationFailed
from common.interfaces import AuditEvent, AuditWriter, UnitOfWork
from common.messages import Messages

AUDIT_OBJECT_USER = "user"


class ProfileService:
    def __init__(
        self,
        *,
        validator: UserValidator,
        users: UserRepository,
        me: MeService,
        audit: AuditWriter,
        uow: UnitOfWork,
    ) -> None:
        self._validator = validator
        self._users = users
        self._me = me
        self._audit = audit
        self._uow = uow

    def update(
        self,
        *,
        user_id: UUID,
        organization_header: str | None,
        sent: dict[str, object],
        ip_address: str | None,
    ) -> Me:
        """Change only the fields the client sent. Nothing sent = nothing written."""
        me = self._me.get_me(user_id, organization_header)
        changes = self._validator.validate_profile(sent)
        _check_quiet_hours(me.user.quiet_hours_start, me.user.quiet_hours_end, changes)
        if not changes:
            return me
        with self._uow.atomic():
            updated = self._users.update_profile(user_id, changes)
            if updated is None:
                raise NotFound()
            self._audit.write(
                AuditEvent(
                    action=AuditAction.USER_PROFILE_UPDATE,
                    actor_type=ActorType.USER,
                    actor_id=user_id,
                    organization_id=me.current.organization.id,
                    object_type=AUDIT_OBJECT_USER,
                    object_id=user_id,
                    # Field names only: a phone number is personal data.
                    details={"fields": sorted(changes)},
                    ip_address=ip_address,
                )
            )
        return replace(me, user=updated)


def _check_quiet_hours(start: object, end: object, changes: dict[str, object]) -> None:
    """Both times set or both empty, judged on the result of the change."""
    if "quiet_hours_start" not in changes and "quiet_hours_end" not in changes:
        return
    final_start = changes.get("quiet_hours_start", start)
    final_end = changes.get("quiet_hours_end", end)
    if (final_start is None) != (final_end is None):
        empty = "quiet_hours_end" if final_end is None else "quiet_hours_start"
        raise ValidationFailed(fields={empty: [FieldIssue(Messages.VALIDATION_QUIET_HOURS_PAIR)]})
