"""Passwords: change while signed in, ask for a reset link, set a new one with the link."""

from uuid import UUID

from apps.accounts.domain.entities import Principal
from apps.accounts.repositories.interfaces import UserRepository
from apps.accounts.services.reset_token_service import ResetTokenService
from apps.accounts.services.session_service import SessionService
from apps.accounts.services.user_validator import UserValidator
from common.attempts import AttemptLimiter
from common.constants import (
    UNKNOWN_IP,
    ActorType,
    AttemptLimits,
    AuditAction,
    HmacNamespace,
    email_subject,
    ip_subject,
    user_subject,
)
from common.errors import Unauthorized, ValidationFailed
from common.interfaces import (
    AuditEvent,
    AuditWriter,
    EmailMessage,
    EmailSender,
    Hasher,
    PasswordHasher,
    UnitOfWork,
)
from common.messages import Messages

AUDIT_OBJECT_USER = "user"


class PasswordService:
    def __init__(
        self,
        *,
        validator: UserValidator,
        users: UserRepository,
        hasher: PasswordHasher,
        digests: Hasher,
        tokens: ResetTokenService,
        sessions: SessionService,
        email: EmailSender,
        audit: AuditWriter,
        uow: UnitOfWork,
        limiter: AttemptLimiter,
        frontend_url: str,
    ) -> None:
        self._validator = validator
        self._users = users
        self._hasher = hasher
        self._digests = digests
        self._tokens = tokens
        self._sessions = sessions
        self._email = email
        self._audit = audit
        self._uow = uow
        self._limiter = limiter
        self._frontend_url = frontend_url

    def change(
        self, *, principal: Principal, current: object, password: object, ip_address: str | None
    ) -> None:
        """Signed-in change. Every other device is signed out; this one stays."""
        # Counted for every attempt: this endpoint is a way to guess the current password.
        self._limiter.hit(AttemptLimits.PASSWORD_CHANGE_USER, user_subject(principal.user_id))
        user = self._users.get(principal.user_id)
        if user is None or not user.is_active:
            raise Unauthorized(Messages.AUTH_ACCESS_TOKEN_INVALID)
        data = self._validator.validate_password_change(
            current=current, password=password, email=user.email, full_name=user.full_name
        )
        if not self._hasher.verify(data.current, user.password_hash):
            raise ValidationFailed.for_field("current", Messages.AUTH_WRONG_CURRENT_PASSWORD)

        # Slow on purpose, so before the transaction opens.
        new_hash = self._hasher.hash(data.password)
        with self._uow.atomic():
            if not self._users.change_password(
                user_id=user.id, expected_hash=user.password_hash, new_hash=new_hash
            ):
                # Someone changed it between our check and our write: the current one is stale.
                raise ValidationFailed.for_field("current", Messages.AUTH_WRONG_CURRENT_PASSWORD)
            self._sessions.revoke_others(user.id, principal.session_id)
            self._audit.write(self._event(AuditAction.USER_PASSWORD_CHANGE, user.id, ip_address))
        self._tell_password_changed(user.email)

    def request_reset(self, *, email: object, ip_address: str | None) -> None:
        """Always returns normally. Only an existing, active account gets a link."""
        self._limiter.hit(AttemptLimits.RESET_IP, ip_subject(ip_address or UNKNOWN_IP))
        clean_email = self._validator.validate_email_only(email=email)
        email_hash = self._digests.digest(HmacNamespace.EMAIL, clean_email)
        self._limiter.hit(AttemptLimits.RESET_EMAIL, email_subject(email_hash))
        user = self._users.get_by_email(clean_email)
        if user is None or not user.is_active:
            return
        token = self._tokens.issue(user)
        self._audit.write(self._event(AuditAction.USER_PASSWORD_RESET_REQUEST, user.id, ip_address))
        self._email.send(
            EmailMessage(
                to=user.email,
                subject=Messages.EMAIL_RESET_LINK_SUBJECT.value,
                text_body=Messages.EMAIL_RESET_LINK_BODY.render(
                    f"{self._frontend_url}/new-password?token={token}"
                ),
            )
        )

    def confirm_reset(self, *, token: object, password: object, ip_address: str | None) -> None:
        """Set a new password with the link. Every device is signed out."""
        self._limiter.hit(AttemptLimits.RESET_CONFIRM_IP, ip_subject(ip_address or UNKNOWN_IP))
        checked = self._validator.check_reset_token(token)
        user_id = self._tokens.user_id_in(checked)
        user = self._users.get(user_id) if user_id else None
        if user is None or not user.is_active or not self._tokens.is_valid(checked, user):
            raise ValidationFailed(Messages.AUTH_INVALID_TOKEN)
        new_password = self._validator.validate_new_password(
            password=password, email=user.email, full_name=user.full_name
        )

        new_hash = self._hasher.hash(new_password)
        with self._uow.atomic():
            if not self._users.change_password(
                user_id=user.id, expected_hash=user.password_hash, new_hash=new_hash
            ):
                raise ValidationFailed(Messages.AUTH_INVALID_TOKEN)  # the link was used meanwhile
            self._sessions.revoke_all(user.id)
            self._audit.write(self._event(AuditAction.USER_PASSWORD_RESET, user.id, ip_address))
        self._tell_password_changed(user.email)

    def _tell_password_changed(self, address: str) -> None:
        self._email.send(
            EmailMessage(
                to=address,
                subject=Messages.EMAIL_PASSWORD_CHANGED_SUBJECT.value,
                text_body=Messages.EMAIL_PASSWORD_CHANGED_BODY.render(
                    f"{self._frontend_url}/sign-in"
                ),
            )
        )

    @staticmethod
    def _event(action: AuditAction, user_id: UUID, ip_address: str | None) -> AuditEvent:
        return AuditEvent(
            action=action,
            actor_type=ActorType.USER,
            actor_id=user_id,
            organization_id=None,
            object_type=AUDIT_OBJECT_USER,
            object_id=user_id,
            ip_address=ip_address,
        )
