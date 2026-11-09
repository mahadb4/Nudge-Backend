"""Sign-in lifecycle: log in with a password, refresh the session, log out."""

from typing import NoReturn

from apps.accounts.domain.entities import SignInResult
from apps.accounts.repositories.interfaces import UserRepository
from apps.accounts.services.me_service import MeService
from apps.accounts.services.session_service import AUDIT_OBJECT_SESSION, SessionService
from apps.accounts.services.user_validator import UserValidator
from common.attempts import AttemptLimiter
from common.constants import (
    UNKNOWN_IP,
    ActorType,
    AttemptLimits,
    AuditAction,
    HmacNamespace,
    Limits,
    email_subject,
    ip_subject,
)
from common.errors import Forbidden, Unauthorized
from common.interfaces import AuditEvent, AuditWriter, Clock, Hasher, PasswordHasher, UnitOfWork
from common.messages import Messages
from common.text import clean, strip_control_chars

AUDIT_OBJECT_USER = "user"


class SignInService:
    def __init__(
        self,
        *,
        validator: UserValidator,
        users: UserRepository,
        hasher: PasswordHasher,
        digests: Hasher,
        sessions: SessionService,
        me: MeService,
        audit: AuditWriter,
        uow: UnitOfWork,
        limiter: AttemptLimiter,
        clock: Clock,
    ) -> None:
        self._validator = validator
        self._users = users
        self._hasher = hasher
        self._digests = digests
        self._sessions = sessions
        self._me = me
        self._audit = audit
        self._uow = uow
        self._limiter = limiter
        self._clock = clock

    def login(
        self,
        *,
        email: object,
        password: object,
        remember: object,
        ip_address: str | None,
        user_agent: str | None,
    ) -> SignInResult:
        self._limiter.hit(AttemptLimits.LOGIN_IP, ip_subject(ip_address or UNKNOWN_IP))
        data = self._validator.validate_login(email=email, password=password, remember=remember)
        email_hash = self._digests.digest(HmacNamespace.EMAIL, data.email)
        # Counted for every attempt, right or wrong: the lock is on the address, not on the result.
        self._limiter.hit(AttemptLimits.LOGIN_EMAIL, email_subject(email_hash))

        user = self._users.get_by_email(data.email)
        if user is None or not user.is_active:
            # Same cost as checking a real password, so timing does not reveal the account.
            self._hasher.dummy_verify(data.password)
            self._refuse(email_hash, ip_address)
        elif not self._hasher.verify(data.password, user.password_hash):
            self._refuse(email_hash, ip_address)
        if user.email_verified_at is None:
            # Only after the password was right, so this does not reveal which emails exist.
            raise Forbidden(Messages.AUTH_EMAIL_UNVERIFIED)

        with self._uow.atomic():
            if self._hasher.needs_rehash(user.password_hash):
                self._users.set_password(user.id, self._hasher.hash(data.password))
            tokens = self._sessions.start(
                user_id=user.id,
                remember=data.remember,
                ip_address=ip_address,
                device_name=_device_name(user_agent),
            )
            self._users.touch_last_login(user.id, self._clock.now())
            me = self._me.get_me(user.id)
            self._audit.write(
                AuditEvent(
                    action=AuditAction.USER_LOGIN,
                    actor_type=ActorType.USER,
                    actor_id=user.id,
                    organization_id=me.current.organization.id,
                    object_type=AUDIT_OBJECT_USER,
                    object_id=user.id,
                    ip_address=ip_address,
                )
            )
        return SignInResult(tokens=tokens, me=me)

    def refresh(self, *, refresh_value: object, ip_address: str | None) -> SignInResult:
        rotation = self._sessions.refresh(refresh_value, ip_address)
        return SignInResult(tokens=rotation.tokens, me=self._me.get_me(rotation.user_id))

    def logout(self, *, refresh_value: object, ip_address: str | None) -> None:
        """Never fails: a missing, wrong or old value just means there is nothing to end."""
        session = self._sessions.end(refresh_value)
        if session is None:
            return
        self._audit.write(
            AuditEvent(
                action=AuditAction.USER_LOGOUT,
                actor_type=ActorType.USER,
                actor_id=session.user_id,
                organization_id=None,
                object_type=AUDIT_OBJECT_SESSION,
                object_id=session.id,
                ip_address=ip_address,
            )
        )

    def _refuse(self, email_hash: str, ip_address: str | None) -> NoReturn:
        self._audit.write(
            AuditEvent(
                action=AuditAction.USER_LOGIN_FAILED,
                actor_type=ActorType.SYSTEM,
                actor_id=None,
                organization_id=None,
                details={"email_hmac": email_hash},
                ip_address=ip_address,
            )
        )
        raise Unauthorized(Messages.AUTH_BAD_CREDENTIALS)


def _device_name(user_agent: str | None) -> str | None:
    """The browser's own description, cleaned and cut to the column size."""
    cleaned = clean(strip_control_chars(user_agent or ""))
    return cleaned[: Limits.DEVICE_NAME] or None
