"""Sign-up. Same answer for every email. A new address gets an account and a code. A known address
that was never verified is overwritten (latest sign-up wins) and gets a fresh code. A verified
address is left alone and only gets a notice."""

from apps.accounts.domain.entities import RegisterData, User
from apps.accounts.domain.errors import DuplicateEmail
from apps.accounts.repositories.interfaces import (
    MembershipRepository,
    OrganizationRepository,
    UserRepository,
)
from apps.accounts.services.interfaces import DefaultStageSeeder
from apps.accounts.services.user_validator import UserValidator
from apps.accounts.services.verification_code_service import VerificationCodeService
from common.attempts import AttemptLimiter
from common.constants import (
    ACCOUNT_TYPE_WIRE,
    UNKNOWN_IP,
    ActorType,
    AttemptLimits,
    AuditAction,
    HmacNamespace,
    Role,
    email_subject,
    ip_subject,
)
from common.errors import ServiceUnavailable
from common.interfaces import (
    AuditEvent,
    AuditWriter,
    EmailMessage,
    EmailSender,
    Hasher,
    IdGenerator,
    PasswordHasher,
    UnitOfWork,
)
from common.messages import Messages

AUDIT_OBJECT_USER = "user"


class RegistrationService:
    def __init__(
        self,
        *,
        validator: UserValidator,
        users: UserRepository,
        organizations: OrganizationRepository,
        memberships: MembershipRepository,
        stage_seeder: DefaultStageSeeder,
        codes: VerificationCodeService,
        email: EmailSender,
        hasher: PasswordHasher,
        digests: Hasher,
        audit: AuditWriter,
        uow: UnitOfWork,
        limiter: AttemptLimiter,
        ids: IdGenerator,
        frontend_url: str,
    ) -> None:
        self._validator = validator
        self._users = users
        self._organizations = organizations
        self._memberships = memberships
        self._stage_seeder = stage_seeder
        self._codes = codes
        self._email = email
        self._hasher = hasher
        self._digests = digests
        self._audit = audit
        self._uow = uow
        self._limiter = limiter
        self._ids = ids
        self._frontend_url = frontend_url

    def register(
        self,
        *,
        name: object,
        company: object,
        email: object,
        password: object,
        account_type: object,
        timezone: object,
        ip_address: str | None,
    ) -> None:
        self._limiter.hit(AttemptLimits.REGISTER_IP, ip_subject(ip_address or UNKNOWN_IP))
        data = self._validator.validate_register(
            name=name,
            company=company,
            email=email,
            password=password,
            account_type=account_type,
            timezone=timezone,
        )
        email_hash = self._digests.digest(HmacNamespace.EMAIL, data.email)
        # Counted for every address, new or known, so a second sign-up within 30 s is refused the
        # same way for both.
        self._limiter.hit(AttemptLimits.RESEND_EMAIL, email_subject(email_hash))

        existing = self._users.get_by_email(data.email)
        if existing is None:
            try:
                user = self._create_account(data, ip_address)
            except DuplicateEmail:
                existing = self._users.get_by_email(
                    data.email
                )  # two sign-ups raced and the other one won
                if existing is None:
                    raise ServiceUnavailable() from None
            else:
                self._codes.send_code(user.email, email_hash)
                return
        self._answer_known_email(existing, data, email_hash, ip_address)

    def _create_account(self, data: RegisterData, ip_address: str | None) -> User:
        # Hashing is slow on purpose, so it happens before the transaction opens (CODING_STYLE 7).
        password_hash = self._hasher.hash(data.password)
        with self._uow.atomic():
            user = self._users.create(
                user_id=self._ids.new_id(),
                email=data.email,
                password_hash=password_hash,
                full_name=data.full_name,
                timezone=data.timezone,
            )
            organization = self._organizations.create(
                organization_id=self._ids.new_id(),
                # A business is named after its company; an individual uses their own name.
                name=data.company or data.full_name,
                account_type=data.account_type,
                timezone=data.timezone,
            )
            self._memberships.create(
                membership_id=self._ids.new_id(),
                organization_id=organization.id,
                user_id=user.id,
                role=Role.OWNER,
            )
            self._stage_seeder.seed_defaults(organization.id)
            self._audit.write(
                AuditEvent(
                    action=AuditAction.USER_REGISTER,
                    actor_type=ActorType.USER,
                    actor_id=user.id,
                    organization_id=organization.id,
                    object_type=AUDIT_OBJECT_USER,
                    object_id=user.id,
                    details={"account_type": ACCOUNT_TYPE_WIRE[data.account_type]},
                    ip_address=ip_address,
                )
            )
        return user

    def _answer_known_email(
        self, existing: User, data: RegisterData, email_hash: str, ip_address: str | None
    ) -> None:
        if existing.email_verified_at is None and self._replace_unverified(
            existing, data, email_hash, ip_address
        ):
            # The latest sign-up wins: the earlier password and code are gone, this code is new.
            self._codes.send_code(existing.email, email_hash)
            return
        self._send_notice(existing, data, email_hash, ip_address)

    def _replace_unverified(
        self, existing: User, data: RegisterData, email_hash: str, ip_address: str | None
    ) -> bool:
        """Overwrite an account whose email nobody has proven yet. False when the owner verified
        it first (then nothing was changed)."""
        # Real hashing, so the work matches a new account. Slow, so before the transaction.
        password_hash = self._hasher.hash(data.password)
        with self._uow.atomic():
            replaced = self._users.replace_registration(
                user_id=existing.id,
                password_hash=password_hash,
                full_name=data.full_name,
                timezone=data.timezone,
            )
            if not replaced:
                return False
            organizations = self._memberships.list_active_for_user(existing.id)
            organization_id = organizations[0].organization.id if organizations else None
            if organization_id is not None:
                self._organizations.update_profile(
                    organization_id=organization_id,
                    name=data.company or data.full_name,
                    account_type=data.account_type,
                    timezone=data.timezone,
                )
            self._audit.write(
                AuditEvent(
                    action=AuditAction.USER_REGISTER_REPLACE,
                    actor_type=ActorType.SYSTEM,
                    actor_id=None,
                    organization_id=organization_id,
                    object_type=AUDIT_OBJECT_USER,
                    object_id=existing.id,
                    details={"email_hmac": email_hash},
                    ip_address=ip_address,
                )
            )
        return True

    def _send_notice(
        self, existing: User, data: RegisterData, email_hash: str, ip_address: str | None
    ) -> None:
        """A verified address changes nothing; its owner only gets told."""
        # Same cost as creating an account, so response time does not reveal that the email is
        # known.
        self._hasher.dummy_verify(data.password)
        self._audit.write(
            AuditEvent(
                action=AuditAction.USER_REGISTER_EXISTING,
                actor_type=ActorType.SYSTEM,
                actor_id=None,
                organization_id=None,
                object_type=AUDIT_OBJECT_USER,
                object_id=existing.id,
                details={"email_hmac": email_hash},
                ip_address=ip_address,
            )
        )
        self._email.send(
            EmailMessage(
                to=existing.email,
                subject=Messages.EMAIL_REGISTER_EXISTING_SUBJECT.value,
                text_body=Messages.EMAIL_REGISTER_EXISTING_BODY.render(
                    f"{self._frontend_url}/sign-in"
                ),
            )
        )
