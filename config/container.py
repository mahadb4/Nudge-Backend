"""Composition root (ARCHITECTURE 5): the only place that builds objects and wires them together.

Controllers call these factories at request time, so tests can replace one with monkeypatch.
Only objects with no dependencies and some cost are cached (hasher, signer, digests). Everything
else is
cheap and stateless, so it is built per call: a test that replaces clock() is seen by everything
built after it.
"""

from functools import cache

from django.conf import settings
from django.core.cache import caches

from apps.accounts.repositories.membership_repository import PostgresMembershipRepository
from apps.accounts.repositories.organization_repository import PostgresOrganizationRepository
from apps.accounts.repositories.session_repository import PostgresSessionRepository
from apps.accounts.repositories.user_repository import PostgresUserRepository
from apps.accounts.repositories.verification_code_repository import CacheVerificationCodeRepository
from apps.accounts.services.authentication_service import AuthenticationService
from apps.accounts.services.me_service import MeService
from apps.accounts.services.organization_service import OrganizationService
from apps.accounts.services.password_service import PasswordService
from apps.accounts.services.profile_service import ProfileService
from apps.accounts.services.registration_service import RegistrationService
from apps.accounts.services.reset_token_service import ResetTokenService
from apps.accounts.services.session_service import SessionService
from apps.accounts.services.sign_in_service import SignInService
from apps.accounts.services.tenant_service import TenantService
from apps.accounts.services.user_validator import UserValidator
from apps.accounts.services.verification_code_service import VerificationCodeService
from apps.accounts.services.verification_service import VerificationService
from apps.audit.repositories.audit_repository import PostgresAuditRepository
from apps.audit.services.audit_service import AuditService
from apps.crm.repositories.company_repository import PostgresCompanyRepository
from apps.crm.repositories.contact_repository import PostgresContactRepository
from apps.crm.repositories.stage_repository import PostgresStageRepository
from apps.crm.services.company_service import CompanyService
from apps.crm.services.company_validator import CompanyValidator
from apps.crm.services.contact_service import ContactService
from apps.crm.services.contact_validator import ContactValidator
from apps.crm.services.link_service import LinkService
from apps.crm.services.stage_service import StageService
from apps.crm.services.stage_validator import StageValidator
from common.attempts import AttemptLimiter
from common.email_templates.renderer import EmailRenderer
from common.health.repositories.health_repository import PostgresHealthRepository
from common.health.services.health_service import HealthService
from common.infra.cache import DjangoCache
from common.infra.clock import SystemClock
from common.infra.email import DjangoEmailSender, HtmlEmailSender, QuietEmailSender
from common.infra.ids import UuidV7Generator
from common.infra.unit_of_work import DjangoUnitOfWork
from common.interfaces import (
    AuditWriter,
    Cache,
    Clock,
    EmailSender,
    Hasher,
    IdGenerator,
    PasswordHasher,
    TokenSigner,
    UnitOfWork,
)
from common.management.demo_seeder import DemoSeeder
from common.security.argon2_password_hasher import Argon2PasswordHasher
from common.security.hmac_hasher import HmacHasher
from common.security.jwt_token_signer import JwtTokenSigner

# -- Infrastructure ----


def clock() -> Clock:
    return SystemClock()


def ids() -> IdGenerator:
    return UuidV7Generator(clock())


def cache_store() -> Cache:
    return DjangoCache(caches["default"])


@cache
def email_renderer() -> EmailRenderer:
    return EmailRenderer(clock())


def email_sender() -> EmailSender:
    """Strict: a delivery failure becomes ServiceUnavailable (503)."""
    return HtmlEmailSender(DjangoEmailSender(), email_renderer())


def quiet_email_sender() -> EmailSender:
    """A failure is logged and swallowed. For paths whose answer must not depend on delivery."""
    return QuietEmailSender(email_sender())


def unit_of_work() -> UnitOfWork:
    return DjangoUnitOfWork()


@cache
def password_hasher() -> PasswordHasher:
    return Argon2PasswordHasher()


@cache
def digests() -> Hasher:
    return HmacHasher(settings.EMAIL_HASH_KEY)


@cache
def token_signer() -> TokenSigner:
    return JwtTokenSigner(settings.JWT_SIGNING_KEY)


def attempt_limiter() -> AttemptLimiter:
    return AttemptLimiter(cache_store(), clock())


# -- Health ----


def health_service() -> HealthService:
    return HealthService(PostgresHealthRepository())


# -- Audit and crm (used by accounts through their interfaces) ----


def audit_writer() -> AuditWriter:
    return AuditService(PostgresAuditRepository(), ids())


def stage_service() -> StageService:
    return StageService(
        PostgresStageRepository(), ids(), audit_writer(), unit_of_work(), StageValidator()
    )


# -- Accounts ----


def verification_code_repository() -> CacheVerificationCodeRepository:
    return CacheVerificationCodeRepository(cache_store(), digests())


def verification_code_service() -> VerificationCodeService:
    return VerificationCodeService(verification_code_repository(), quiet_email_sender())


def me_service() -> MeService:
    return MeService(PostgresUserRepository(), PostgresMembershipRepository())


def session_service() -> SessionService:
    return SessionService(
        sessions=PostgresSessionRepository(),
        users=PostgresUserRepository(),
        signer=token_signer(),
        ids=ids(),
        clock=clock(),
        audit=audit_writer(),
        uow=unit_of_work(),
    )


def tenant_service() -> TenantService:
    return TenantService(PostgresMembershipRepository())


def authentication_service() -> AuthenticationService:
    return AuthenticationService(token_signer(), PostgresSessionRepository(), clock())


def sign_in_service() -> SignInService:
    return SignInService(
        validator=UserValidator(),
        users=PostgresUserRepository(),
        hasher=password_hasher(),
        digests=digests(),
        sessions=session_service(),
        me=me_service(),
        audit=audit_writer(),
        uow=unit_of_work(),
        limiter=attempt_limiter(),
        clock=clock(),
    )


def registration_service() -> RegistrationService:
    return RegistrationService(
        validator=UserValidator(),
        users=PostgresUserRepository(),
        organizations=PostgresOrganizationRepository(),
        memberships=PostgresMembershipRepository(),
        stage_seeder=stage_service(),
        codes=verification_code_service(),
        email=quiet_email_sender(),
        hasher=password_hasher(),
        digests=digests(),
        audit=audit_writer(),
        uow=unit_of_work(),
        limiter=attempt_limiter(),
        ids=ids(),
        frontend_url=settings.FRONTEND_URL,
    )


def verification_service() -> VerificationService:
    return VerificationService(
        validator=UserValidator(),
        users=PostgresUserRepository(),
        codes=verification_code_repository(),
        code_sender=verification_code_service(),
        sessions=session_service(),
        me=me_service(),
        digests=digests(),
        audit=audit_writer(),
        uow=unit_of_work(),
        limiter=attempt_limiter(),
        clock=clock(),
    )


def reset_token_service() -> ResetTokenService:
    return ResetTokenService(digests(), clock())


def password_service() -> PasswordService:
    return PasswordService(
        validator=UserValidator(),
        users=PostgresUserRepository(),
        hasher=password_hasher(),
        digests=digests(),
        tokens=reset_token_service(),
        sessions=session_service(),
        email=quiet_email_sender(),
        audit=audit_writer(),
        uow=unit_of_work(),
        limiter=attempt_limiter(),
        frontend_url=settings.FRONTEND_URL,
    )


def profile_service() -> ProfileService:
    return ProfileService(
        validator=UserValidator(),
        users=PostgresUserRepository(),
        me=me_service(),
        audit=audit_writer(),
        uow=unit_of_work(),
    )


def organization_service() -> OrganizationService:
    return OrganizationService(
        validator=UserValidator(),
        organizations=PostgresOrganizationRepository(),
        audit=audit_writer(),
        uow=unit_of_work(),
    )


def company_service() -> CompanyService:
    return CompanyService(
        PostgresCompanyRepository(),
        ids(),
        audit_writer(),
        unit_of_work(),
        CompanyValidator(),
        clock(),
        LinkService(PostgresCompanyRepository()),
    )


def contact_service() -> ContactService:
    return ContactService(
        PostgresContactRepository(),
        ids(),
        audit_writer(),
        unit_of_work(),
        ContactValidator(),
        clock(),
        LinkService(PostgresContactRepository()),
    )


def demo_seeder() -> DemoSeeder:
    return DemoSeeder(
        users=PostgresUserRepository(),
        organizations=PostgresOrganizationRepository(),
        memberships=PostgresMembershipRepository(),
        stages=stage_service(),
        companies=company_service(),
        contacts=contact_service(),
        hasher=password_hasher(),
        ids=ids(),
        clock=clock(),
        uow=unit_of_work(),
    )
