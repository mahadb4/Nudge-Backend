"""Business objects of accounts. Frozen dataclasses, no framework, never sent to the client
directly."""

from dataclasses import dataclass
from datetime import datetime, time
from uuid import UUID

from apps.accounts.domain.enums import MembershipStatus
from common.constants import AccountType, Role


@dataclass(frozen=True, slots=True)
class User:
    id: UUID
    email: str
    password_hash: str
    full_name: str
    phone: str | None
    timezone: str
    is_active: bool
    email_verified_at: datetime | None
    last_login: datetime | None
    created_at: datetime
    quiet_hours_start: time | None = None
    quiet_hours_end: time | None = None


@dataclass(frozen=True, slots=True)
class Organization:
    id: UUID
    name: str
    account_type: AccountType
    timezone: str
    created_at: datetime
    automation_paused: bool = False


@dataclass(frozen=True, slots=True)
class Membership:
    id: UUID
    organization_id: UUID
    user_id: UUID
    role: Role
    status: MembershipStatus


@dataclass(frozen=True, slots=True)
class MembershipWithOrganization:
    membership: Membership
    organization: Organization


@dataclass(frozen=True, slots=True)
class Session:
    id: UUID
    user_id: UUID
    refresh_token_hash: str
    device_name: str | None
    ip_address: str | None
    expires_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class SessionTokens:
    """What a new session hands to the client: the access token in the body, the refresh value in a
    cookie."""

    access_token: str
    refresh_value: str
    cookie_max_age: int | None  # seconds; None = a browser-session cookie


@dataclass(frozen=True, slots=True)
class Me:
    """The signed-in user with every organization they belong to. current is the one being used."""

    user: User
    current: MembershipWithOrganization
    organizations: tuple[MembershipWithOrganization, ...]


@dataclass(frozen=True, slots=True)
class SignInResult:
    """What verify, login and refresh hand back: new tokens and the signed-in user."""

    tokens: SessionTokens
    me: Me


@dataclass(frozen=True, slots=True)
class Rotation:
    """The result of swapping a refresh value: whose session it is and its new tokens."""

    user_id: UUID
    tokens: SessionTokens


@dataclass(frozen=True, slots=True)
class Principal:
    """Who an access token belongs to: the user and the session (device) it was issued for."""

    user_id: UUID
    session_id: UUID


@dataclass(frozen=True, slots=True)
class PasswordChangeData:
    current: str
    password: str


@dataclass(frozen=True, slots=True)
class LoginData:
    email: str
    password: str
    remember: bool


@dataclass(frozen=True, slots=True)
class RegisterData:
    """Sign-up input after validation: cleaned, normalised, checked."""

    full_name: str
    company: str | None
    email: str
    password: str
    account_type: AccountType
    timezone: str


@dataclass(frozen=True, slots=True)
class VerifyData:
    email: str
    code: str
