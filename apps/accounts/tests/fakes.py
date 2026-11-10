"""In-memory fakes of the accounts repositories, and a 'world' that wires the real services to them.

Used by the service unit tests: no database, no HTTP, time moves only when a test says so.
"""

import re
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

from apps.accounts.domain.entities import (
    Membership,
    MembershipWithOrganization,
    Organization,
    Session,
    SignInResult,
    User,
)
from apps.accounts.domain.enums import MembershipStatus
from apps.accounts.domain.errors import DuplicateEmail
from apps.accounts.repositories.verification_code_repository import CacheVerificationCodeRepository
from apps.accounts.services.authentication_service import AuthenticationService
from apps.accounts.services.me_service import MeService
from apps.accounts.services.password_service import PasswordService
from apps.accounts.services.registration_service import RegistrationService
from apps.accounts.services.reset_token_service import ResetTokenService
from apps.accounts.services.session_service import SessionService
from apps.accounts.services.sign_in_service import SignInService
from apps.accounts.services.tenant_service import TenantService
from apps.accounts.services.user_validator import UserValidator
from apps.accounts.services.verification_code_service import VerificationCodeService
from apps.accounts.services.verification_service import VerificationService
from common.attempts import AttemptLimiter
from common.constants import AccountType, Role
from common.security.hmac_hasher import HmacHasher
from common.security.jwt_token_signer import JwtTokenSigner
from common.tenancy import TenantContext
from common.tests.fakes import (
    FakeAuditWriter,
    FakeCache,
    FakeEmailSender,
    FakePasswordHasher,
    FakeUnitOfWork,
    FrozenClock,
    SequentialIdGenerator,
)

START = datetime(2026, 11, 9, 12, 0, 0, tzinfo=UTC)
FRONTEND_URL = "https://app.nudge.test"
VALID_REGISTRATION = dict(
    name="Ali Raza",
    company="Acme Sales",
    email="ali@example.com",
    password="Harbor-Lantern-42",
    account_type="business",
    timezone="Asia/Karachi",
)


class FakeUserRepository:
    def __init__(self, clock: FrozenClock) -> None:
        self._clock = clock
        self.rows: dict[UUID, User] = {}
        # Simulate: another request creates the same email just before ours.
        self.race_on_next_create = False
        # Simulate: the owner verifies the email just before replace_registration runs.
        self.verify_before_next_update: datetime | None = None

    def get(self, user_id: UUID) -> User | None:
        return self.rows.get(user_id)

    def get_by_email(self, email: str) -> User | None:
        return next((u for u in self.rows.values() if u.email == email), None)

    def email_exists(self, email: str) -> bool:
        return self.get_by_email(email) is not None

    def create(
        self, *, user_id: UUID, email: str, password_hash: str, full_name: str, timezone: str
    ) -> User:
        if self.race_on_next_create:
            self.race_on_next_create = False
            self._insert(UUID(int=999_999), email, "x", "Winner", timezone)
            raise DuplicateEmail()
        if self.email_exists(email):
            raise DuplicateEmail()
        return self._insert(user_id, email, password_hash, full_name, timezone)

    def _insert(
        self, user_id: UUID, email: str, password_hash: str, full_name: str, timezone: str
    ) -> User:
        user = User(
            user_id,
            email,
            password_hash,
            full_name,
            None,
            timezone,
            True,
            None,
            None,
            self._clock.now(),
        )
        self.rows[user_id] = user
        return user

    def replace_registration(
        self, *, user_id: UUID, password_hash: str, full_name: str, timezone: str
    ) -> bool:
        if self.verify_before_next_update is not None:
            # Simulate: the owner verified just before this update ran.
            self.mark_email_verified(user_id, self.verify_before_next_update)
            self.verify_before_next_update = None
        user = self.rows[user_id]
        if user.email_verified_at is not None:
            return False
        self.rows[user_id] = replace(
            user, password_hash=password_hash, full_name=full_name, timezone=timezone
        )
        return True

    def mark_email_verified(self, user_id: UUID, at: datetime) -> bool:
        user = self.rows[user_id]
        if user.email_verified_at is not None:
            return False
        self.rows[user_id] = replace(user, email_verified_at=at)
        return True

    def set_password(self, user_id: UUID, password_hash: str) -> None:
        self.rows[user_id] = replace(self.rows[user_id], password_hash=password_hash)

    def update_profile(self, user_id: UUID, changes: Mapping[str, object]) -> User | None:
        user = self.rows.get(user_id)
        if user is None:
            return None
        self.rows[user_id] = replace(user, **changes)
        return self.rows[user_id]

    def change_password(self, *, user_id: UUID, expected_hash: str, new_hash: str) -> bool:
        user = self.rows[user_id]
        if user.password_hash != expected_hash:
            return False
        self.rows[user_id] = replace(user, password_hash=new_hash)
        return True

    def touch_last_login(self, user_id: UUID, at: datetime) -> None:
        self.rows[user_id] = replace(self.rows[user_id], last_login=at)


class FakeOrganizationRepository:
    def __init__(self, clock: FrozenClock) -> None:
        self._clock = clock
        self.rows: dict[UUID, Organization] = {}

    def get(self, organization_id: UUID) -> Organization | None:
        return self.rows.get(organization_id)

    def create(
        self, *, organization_id: UUID, name: str, account_type: AccountType, timezone: str
    ) -> Organization:
        organization = Organization(
            organization_id, name, account_type, timezone, self._clock.now()
        )
        self.rows[organization_id] = organization
        return organization

    def update_settings(
        self, organization_id: UUID, changes: Mapping[str, object]
    ) -> Organization | None:
        organization = self.rows.get(organization_id)
        if organization is None:
            return None
        self.rows[organization_id] = replace(organization, **changes)
        return self.rows[organization_id]

    def update_profile(
        self, *, organization_id: UUID, name: str, account_type: AccountType, timezone: str
    ) -> None:
        self.rows[organization_id] = replace(
            self.rows[organization_id], name=name, account_type=account_type, timezone=timezone
        )


class FakeMembershipRepository:
    def __init__(self, organizations: FakeOrganizationRepository) -> None:
        self._organizations = organizations
        self.rows: list[Membership] = []

    def create(
        self, *, membership_id: UUID, organization_id: UUID, user_id: UUID, role: Role
    ) -> Membership:
        membership = Membership(
            membership_id, organization_id, user_id, role, MembershipStatus.ACTIVE
        )
        self.rows.append(membership)
        return membership

    def get_active(self, organization_id: UUID, user_id: UUID) -> Membership | None:
        return next(
            (
                m
                for m in self.rows
                if m.organization_id == organization_id
                and m.user_id == user_id
                and m.status is MembershipStatus.ACTIVE
            ),
            None,
        )

    def list_active_for_user(self, user_id: UUID) -> list[MembershipWithOrganization]:
        return [
            MembershipWithOrganization(m, self._organizations.rows[m.organization_id])
            for m in self.rows
            if m.user_id == user_id and m.status is MembershipStatus.ACTIVE
        ]


class FakeSessionRepository:
    def __init__(self, clock: FrozenClock) -> None:
        self._clock = clock
        self.rows: dict[UUID, Session] = {}

    def create(
        self,
        *,
        session_id: UUID,
        user_id: UUID,
        refresh_token_hash: str,
        device_name: str | None,
        ip_address: str | None,
        expires_at: datetime,
    ) -> Session:
        session = Session(
            session_id,
            user_id,
            refresh_token_hash,
            device_name,
            ip_address,
            expires_at,
            None,
            None,
            self._clock.now(),
        )
        self.rows[session_id] = session
        return session

    def get(self, session_id: UUID) -> Session | None:
        return self.rows.get(session_id)

    def get_active(self, session_id: UUID, now: datetime) -> Session | None:
        session = self.rows.get(session_id)
        return (
            session if session and session.revoked_at is None and session.expires_at > now else None
        )

    def rotate(self, *, session_id: UUID, old_hash: str, new_hash: str, now: datetime) -> bool:
        session = self.get_active(session_id, now)
        if session is None or session.refresh_token_hash != old_hash:
            return False
        self.rows[session_id] = replace(session, refresh_token_hash=new_hash, last_used_at=now)
        return True

    def revoke(self, session_id: UUID, now: datetime) -> bool:
        session = self.rows.get(session_id)
        if session is None or session.revoked_at is not None:
            return False
        self.rows[session_id] = replace(session, revoked_at=now)
        return True

    def revoke_all(
        self, user_id: UUID, now: datetime, except_session_id: UUID | None = None
    ) -> int:
        targets = [
            s
            for s in self.rows.values()
            if s.user_id == user_id and s.revoked_at is None and s.id != except_session_id
        ]
        for session in targets:
            self.rows[session.id] = replace(session, revoked_at=now)
        return len(targets)


class FakeStageSeeder:
    def __init__(self) -> None:
        self.seeded: list[TenantContext] = []
        self.error: Exception | None = None

    def seed_defaults(self, context: TenantContext) -> list[object]:
        if self.error is not None:
            raise self.error
        self.seeded.append(context)
        return []


class AccountsWorld:
    """The real services wired to fakes. Reach into it to arrange and to assert."""

    def __init__(self) -> None:
        self.clock = FrozenClock(START)
        self.cache = FakeCache(self.clock)
        self.limiter = AttemptLimiter(self.cache, self.clock)
        self.hasher = FakePasswordHasher()
        self.digests = HmacHasher("test-hmac-key")
        self.email = FakeEmailSender()
        self.audit = FakeAuditWriter()
        self.uow = FakeUnitOfWork()
        self.ids = SequentialIdGenerator()
        self.users = FakeUserRepository(self.clock)
        self.organizations = FakeOrganizationRepository(self.clock)
        self.memberships = FakeMembershipRepository(self.organizations)
        self.sessions = FakeSessionRepository(self.clock)
        self.seeder = FakeStageSeeder()
        self.signer = JwtTokenSigner("test-signing-key-that-is-long-enough-for-hs256")
        self.code_repository = CacheVerificationCodeRepository(self.cache, self.digests)
        self.code_service = VerificationCodeService(self.code_repository, self.email)
        self.session_service = SessionService(
            sessions=self.sessions,
            users=self.users,
            signer=self.signer,
            ids=self.ids,
            clock=self.clock,
            audit=self.audit,
            uow=self.uow,
        )
        self.me_service = MeService(self.users, self.memberships)
        self.registration = RegistrationService(
            validator=UserValidator(),
            users=self.users,
            organizations=self.organizations,
            memberships=self.memberships,
            stage_seeder=self.seeder,
            codes=self.code_service,
            email=self.email,
            hasher=self.hasher,
            digests=self.digests,
            audit=self.audit,
            uow=self.uow,
            limiter=self.limiter,
            ids=self.ids,
            frontend_url=FRONTEND_URL,
        )
        self.verification = VerificationService(
            validator=UserValidator(),
            users=self.users,
            codes=self.code_repository,
            code_sender=self.code_service,
            sessions=self.session_service,
            me=self.me_service,
            digests=self.digests,
            audit=self.audit,
            uow=self.uow,
            limiter=self.limiter,
            clock=self.clock,
        )

        self.sign_in = SignInService(
            validator=UserValidator(),
            users=self.users,
            hasher=self.hasher,
            digests=self.digests,
            sessions=self.session_service,
            me=self.me_service,
            audit=self.audit,
            uow=self.uow,
            limiter=self.limiter,
            clock=self.clock,
        )
        self.authentication = AuthenticationService(self.signer, self.sessions, self.clock)
        self.tenant = TenantService(self.memberships)
        self.reset_tokens = ResetTokenService(self.digests, self.clock)
        self.passwords = PasswordService(
            validator=UserValidator(),
            users=self.users,
            hasher=self.hasher,
            digests=self.digests,
            tokens=self.reset_tokens,
            sessions=self.session_service,
            email=self.email,
            audit=self.audit,
            uow=self.uow,
            limiter=self.limiter,
            frontend_url=FRONTEND_URL,
        )

    def verified_user(self, **overrides: object) -> SignInResult:
        """Register and verify an account, then move past the 30 second resend window."""
        self.register(**overrides)
        email = str(overrides.get("email", VALID_REGISTRATION["email"]))
        self.clock.advance(31)
        return self.verification.verify(
            email=email, code=self.last_code(), ip_address="203.0.113.9"
        )

    def register(self, **overrides: object) -> None:
        self.registration.register(
            **{**VALID_REGISTRATION, "ip_address": "203.0.113.9", **overrides}
        )

    def last_code(self) -> str:
        match = re.search(r"Your code is (\d{6})\.", self.email.outbox[-1].text_body)
        assert match, "the last email carries no code"
        return match.group(1)
