"""Names, lifetimes, limits and codes used in logic (ARCHITECTURE 4). Framework-free.

Plain values and plain functions only. Anything that touches the database, cache, clock or email is
an
injected object, never a function here.
"""

import re
from dataclasses import dataclass
from enum import IntEnum, StrEnum
from types import MappingProxyType
from uuid import UUID

API_PREFIX = "/api/v1/"
KEY_PREFIX = "nudge"


class Header:
    AUTHORIZATION = "Authorization"
    CSRF = "X-CSRFToken"
    ORGANIZATION = "X-Organization-ID"
    RETRY_AFTER = "Retry-After"
    CACHE_CONTROL = "Cache-Control"


class MetaKey:
    """Where Django's request.META keeps some request headers."""

    AUTHORIZATION = "HTTP_AUTHORIZATION"
    USER_AGENT = "HTTP_USER_AGENT"
    FORWARDED_FOR = "HTTP_X_FORWARDED_FOR"
    ORGANIZATION = "HTTP_X_ORGANIZATION_ID"
    REMOTE_ADDR = "REMOTE_ADDR"


class HeaderValue:
    NO_STORE = "no-store"
    BEARER_PREFIX = "Bearer "


class HealthStatus:
    OK = "ok"
    DOWN = "unavailable"


class EmailKind(StrEnum):
    """The designed (HTML) emails. Each has a template in common/email_templates/."""

    VERIFY_CODE = "verify_code"
    REGISTER_EXISTING = "register_existing"
    RESET_LINK = "reset_link"


class HmacNamespace:
    """Domain separation for the one HMAC key: the same value hashed for two purposes gives two
    digests."""

    EMAIL = "email"
    VERIFY_CODE = "verify_code"
    RESET_TOKEN = "reset_token"


class TokenClaim:
    USER_ID = "user_id"
    SESSION_ID = "sid"
    JTI = "jti"
    ISSUED_AT = "iat"
    EXPIRES_AT = "exp"


UNKNOWN_IP = "unknown"  # rate-limit subject when the client address cannot be determined
JWT_ALGORITHM = "HS256"
SAFE_FIELD_NAME = re.compile(
    r"[A-Za-z0-9_]{1,40}"
)  # field names echoed back to the client must match this
SECURE_COOKIE_SAMESITE = "Lax"


class Cookie:
    REFRESH = "nudge_refresh"
    REFRESH_PATH = "/api/v1/auth/"
    CSRF = "csrftoken"


class Ttl:
    """Lifetimes in seconds."""

    ACCESS_TOKEN = 10 * 60
    REFRESH_REMEMBER = 30 * 24 * 3600
    REFRESH_SESSION = 24 * 3600
    # A session that lives longer than this was created with 'keep me signed in'. Midway between 1
    # and 30 days, so a few seconds of clock difference between app and database cannot flip it.
    REMEMBER_MIN_LIFETIME = 10 * 24 * 3600
    VERIFY_CODE = 10 * 60
    RESET_LINK = 3600


class AuthRules:
    CODE_LENGTH = 6
    CODE_MAX_TRIES = 5
    RESEND_INTERVAL = 30


class Limits:
    """Field limits. Where the frontend is stricter than the column, the frontend wins (Q-30)."""

    NAME_MIN = 2
    NAME = 80
    COMPANY_MIN = 2
    COMPANY = 120
    EMAIL = 254
    EMAIL_LOCAL = 64
    PASSWORD_MIN = 8
    PASSWORD_MAX = 128
    TIMEZONE = 64
    DEVICE_NAME = 100  # user_sessions.device_name
    RESET_TOKEN_MIN = 4
    RESET_TOKEN_MAX = 200
    BODY_BYTES = 1_000_000
    PAGE_SIZE_DEFAULT = 25
    PAGE_SIZE_MAX = 100  # hard cap on every list (CODING_STYLE 7)
    STAGE_NAME = 40
    DOMAIN = 253
    INDUSTRY = 80
    PERSON_NAME_PART = 80
    JOB_TITLE = 80
    STAGES_MAX = 12
    QUERY_MIN = 2
    QUERY_MAX = 100


@dataclass(frozen=True, slots=True)
class AttemptLimit:
    """A simple fixed-window attempt limit for the midterm (full token bucket after the midterm)."""

    name: str
    max_attempts: int
    window_seconds: int


class AttemptLimits:
    LOGIN_EMAIL = AttemptLimit("login_email", 5, 60)
    LOGIN_IP = AttemptLimit("login_ip", 20, 60)
    RESEND_EMAIL = AttemptLimit("resend_email", 1, AuthRules.RESEND_INTERVAL)
    VERIFY_IP = AttemptLimit("verify_ip", 20, 60)
    REGISTER_IP = AttemptLimit("register_ip", 10, 3600)
    RESET_EMAIL = AttemptLimit("reset_email", 3, 3600)
    RESET_IP = AttemptLimit("reset_ip", 10, 3600)
    RESET_CONFIRM_IP = AttemptLimit("reset_confirm_ip", 10, 3600)
    PASSWORD_CHANGE_USER = AttemptLimit("password_change_user", 5, 900)


class Role(IntEnum):
    OWNER = 1
    ADMIN = 2
    MANAGER = 3
    MEMBER = 4


ROLE_WIRE = MappingProxyType(
    {Role.OWNER: "owner", Role.ADMIN: "admin", Role.MANAGER: "manager", Role.MEMBER: "member"}
)


class AccountType(IntEnum):
    INDIVIDUAL = 1
    BUSINESS = 2


ACCOUNT_TYPE_WIRE = MappingProxyType(
    {AccountType.INDIVIDUAL: "individual", AccountType.BUSINESS: "business"}
)
ACCOUNT_TYPE_BY_WIRE = MappingProxyType({wire: value for value, wire in ACCOUNT_TYPE_WIRE.items()})


class ActorType(IntEnum):
    USER = 1
    SYSTEM = 2
    AI = 3


class AuditAction(StrEnum):
    """audit_logs.action values; the database CHECK requires 'object.verb'."""

    USER_REGISTER = "user.register"
    USER_REGISTER_EXISTING = "user.register_existing"
    USER_REGISTER_REPLACE = "user.register_replace"
    USER_EMAIL_VERIFY = "user.email_verify"
    USER_LOGIN = "user.login"
    USER_LOGIN_FAILED = "user.login_failed"
    USER_LOGOUT = "user.logout"
    USER_PASSWORD_CHANGE = "user.password_change"
    USER_PASSWORD_RESET_REQUEST = "user.password_reset_request"
    USER_PASSWORD_RESET = "user.password_reset"
    SESSION_REVOKE = "session.revoke"
    SESSION_REUSE_DETECTED = "session.reuse_detected"
    USER_PROFILE_UPDATE = "user.profile_update"
    ORGANIZATION_UPDATE = "organization.update"
    CONTACT_CREATE = "contact.create"
    CONTACT_UPDATE = "contact.update"
    CONTACT_DELETE = "contact.delete"
    COMPANY_CREATE = "company.create"
    COMPANY_UPDATE = "company.update"
    COMPANY_DELETE = "company.delete"
    DEAL_STAGE_CREATE = "deal_stage.create"
    DEAL_STAGE_UPDATE = "deal_stage.update"
    DEAL_STAGE_REORDER = "deal_stage.reorder"
    DEAL_STAGE_DELETE = "deal_stage.delete"


_HEX_DIGEST = re.compile(r"[0-9a-f]{64}")


def _checked_digest(value: str) -> str:
    if not _HEX_DIGEST.fullmatch(value):
        raise ValueError("expected a 64-character hex HMAC, never a raw email")
    return value


def verify_code_key(email_hmac: str) -> str:
    return f"{KEY_PREFIX}:verify_code:{_checked_digest(email_hmac)}"


def verify_tries_key(email_hmac: str) -> str:
    return f"{KEY_PREFIX}:verify_tries:{_checked_digest(email_hmac)}"


def attempt_key(limit: AttemptLimit, subject: str, window_index: int) -> str:
    return f"{KEY_PREFIX}:attempts:{limit.name}:{subject}:{window_index}"


def ip_subject(address: str) -> str:
    return f"ip:{address}"


def email_subject(email_hmac: str) -> str:
    """Takes the HMAC of the email, never the address, so no email is stored in a cache key."""
    return f"email:{_checked_digest(email_hmac)}"


def user_subject(user_id: UUID) -> str:
    return f"user:{user_id}"
