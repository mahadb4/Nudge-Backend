"""Email verification: check the code, mark the email verified, sign the user in. Also resending a
code."""

from apps.accounts.domain.entities import SignInResult
from apps.accounts.domain.enums import CodeCheck
from apps.accounts.repositories.interfaces import UserRepository, VerificationCodeRepository
from apps.accounts.services.me_service import MeService
from apps.accounts.services.session_service import SessionService
from apps.accounts.services.user_validator import UserValidator
from apps.accounts.services.verification_code_service import VerificationCodeService
from common.attempts import AttemptLimiter
from common.constants import (
    UNKNOWN_IP,
    ActorType,
    AttemptLimits,
    AuditAction,
    AuthRules,
    HmacNamespace,
    email_subject,
    ip_subject,
)
from common.errors import RateLimited, ValidationFailed
from common.interfaces import AuditEvent, AuditWriter, Clock, Hasher, UnitOfWork
from common.messages import Messages

AUDIT_OBJECT_USER = "user"


class VerificationService:
    def __init__(
        self,
        *,
        validator: UserValidator,
        users: UserRepository,
        codes: VerificationCodeRepository,
        code_sender: VerificationCodeService,
        sessions: SessionService,
        me: MeService,
        digests: Hasher,
        audit: AuditWriter,
        uow: UnitOfWork,
        limiter: AttemptLimiter,
        clock: Clock,
    ) -> None:
        self._validator = validator
        self._users = users
        self._codes = codes
        self._code_sender = code_sender
        self._sessions = sessions
        self._me = me
        self._digests = digests
        self._audit = audit
        self._uow = uow
        self._limiter = limiter
        self._clock = clock

    def verify(self, *, email: object, code: object, ip_address: str | None) -> SignInResult:
        self._limiter.hit(AttemptLimits.VERIFY_IP, ip_subject(ip_address or UNKNOWN_IP))
        data = self._validator.validate_verify(email=email, code=code)
        email_hash = self._digests.digest(HmacNamespace.EMAIL, data.email)

        outcome = self._codes.check(email_hash, data.code)
        if outcome is CodeCheck.LOCKED:
            raise RateLimited(
                Messages.AUTH_CODE_ATTEMPTS_EXCEEDED, retry_after=AuthRules.RESEND_INTERVAL
            )
        user = self._users.get_by_email(data.email)
        # One answer for a wrong code, an expired code, no code and an unknown email.
        if outcome is not CodeCheck.OK or user is None or not user.is_active:
            raise ValidationFailed(Messages.AUTH_INVALID_CODE)

        with self._uow.atomic():
            self._users.mark_email_verified(user.id, self._clock.now())
            self._codes.discard(email_hash)
            # remember=False: a session cookie and a 1-day session. "Keep me signed in" belongs to
            # the login form.
            tokens = self._sessions.start(
                user_id=user.id, remember=False, ip_address=ip_address, device_name=None
            )
            me = self._me.get_me(user.id)
            self._audit.write(
                AuditEvent(
                    action=AuditAction.USER_EMAIL_VERIFY,
                    actor_type=ActorType.USER,
                    actor_id=user.id,
                    organization_id=me.current.organization.id,
                    object_type=AUDIT_OBJECT_USER,
                    object_id=user.id,
                    ip_address=ip_address,
                )
            )
        return SignInResult(tokens=tokens, me=me)

    def resend(self, *, email: object, ip_address: str | None) -> None:
        """Always returns normally. Only an unverified, existing account gets a new code."""
        self._limiter.hit(AttemptLimits.VERIFY_IP, ip_subject(ip_address or UNKNOWN_IP))
        clean_email = self._validator.validate_email_only(email=email)
        email_hash = self._digests.digest(HmacNamespace.EMAIL, clean_email)
        self._limiter.hit(AttemptLimits.RESEND_EMAIL, email_subject(email_hash))
        user = self._users.get_by_email(clean_email)
        if user is not None and user.is_active and user.email_verified_at is None:
            self._code_sender.send_code(user.email, email_hash)
