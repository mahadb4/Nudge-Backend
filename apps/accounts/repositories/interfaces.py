"""What the accounts services need from storage. Services depend on these Protocols, never on the
ORM."""

from collections.abc import Mapping
from datetime import datetime
from typing import Protocol
from uuid import UUID

from apps.accounts.domain.entities import (
    Membership,
    MembershipWithOrganization,
    Organization,
    Session,
    User,
)
from apps.accounts.domain.enums import CodeCheck
from common.constants import AccountType, Role


class UserRepository(Protocol):
    def get(self, user_id: UUID) -> User | None: ...

    def get_by_email(self, email: str) -> User | None:
        """The email must already be normalised (lower case)."""
        ...

    def email_exists(self, email: str) -> bool: ...

    def create(
        self, *, user_id: UUID, email: str, password_hash: str, full_name: str, timezone: str
    ) -> User:
        """Raises DuplicateEmail when the email is taken, also when two requests race."""
        ...

    def replace_registration(
        self, *, user_id: UUID, password_hash: str, full_name: str, timezone: str
    ) -> bool:
        """Overwrite password, name and timezone, but only while the email is still unverified.
        False = it was verified in the meantime and nothing changed."""
        ...

    def mark_email_verified(self, user_id: UUID, at: datetime) -> bool:
        """True when this call verified the email; False when it was already verified."""
        ...

    def set_password(self, user_id: UUID, password_hash: str) -> None: ...

    def update_profile(self, user_id: UUID, changes: Mapping[str, object]) -> User | None:
        """Write only the named profile fields (full_name, phone, timezone, quiet_hours_start,
        quiet_hours_end) and return the user as stored."""
        ...

    def change_password(self, *, user_id: UUID, expected_hash: str, new_hash: str) -> bool:
        """Replace the password only if it is still the one the caller checked. False = it changed
        in the meantime (two requests at once, or a reset link used twice)."""
        ...

    def touch_last_login(self, user_id: UUID, at: datetime) -> None: ...


class OrganizationRepository(Protocol):
    def get(self, organization_id: UUID) -> Organization | None: ...

    def get_by_name(self, name: str) -> Organization | None:
        """The oldest open organization with exactly this name."""
        ...

    def create(
        self, *, organization_id: UUID, name: str, account_type: AccountType, timezone: str
    ) -> Organization: ...

    def update_profile(
        self, *, organization_id: UUID, name: str, account_type: AccountType, timezone: str
    ) -> None: ...

    def update_settings(
        self, organization_id: UUID, changes: Mapping[str, object]
    ) -> Organization | None:
        """Write only name and/or timezone and return the organization as stored."""
        ...


class MembershipRepository(Protocol):
    def create(
        self, *, membership_id: UUID, organization_id: UUID, user_id: UUID, role: Role
    ) -> Membership: ...

    def find_owner_user_id(self, organization_id: UUID) -> UUID | None:
        """The oldest active Owner of the organization."""
        ...

    def get_active(self, organization_id: UUID, user_id: UUID) -> Membership | None:
        """The user's active membership in exactly this organization, or None (tenant check)."""
        ...

    def list_active_for_user(self, user_id: UUID) -> list[MembershipWithOrganization]:
        """Active memberships in organizations that are not closed, oldest first."""
        ...


class SessionRepository(Protocol):
    def create(
        self,
        *,
        session_id: UUID,
        user_id: UUID,
        refresh_token_hash: str,
        device_name: str | None,
        ip_address: str | None,
        expires_at: datetime,
    ) -> Session: ...

    def get(self, session_id: UUID) -> Session | None:
        """Any session, also revoked or expired ones (needed to detect reuse of an old refresh
        value)."""
        ...

    def get_active(self, session_id: UUID, now: datetime) -> Session | None:
        """The session only while it is not revoked and not expired."""
        ...

    def rotate(self, *, session_id: UUID, old_hash: str, new_hash: str, now: datetime) -> bool:
        """Replace the refresh hash only if the old hash still matches (a conditional update). False
        = lost the race."""
        ...

    def revoke(self, session_id: UUID, now: datetime) -> bool: ...

    def revoke_all(
        self, user_id: UUID, now: datetime, except_session_id: UUID | None = None
    ) -> int: ...


class VerificationCodeRepository(Protocol):
    """Email verification codes. Kept in the shared cache (not in a table) for 10 minutes. Keyed by
    the email's HMAC."""

    def issue(self, email_hash: str) -> str:
        """A new 6-digit code. Replaces any earlier code and resets the wrong-try counter."""
        ...

    def check(self, email_hash: str, code: str) -> CodeCheck:
        """OK, WRONG (counts one try) or LOCKED (5 wrong tries used). Does not remove the code."""
        ...

    def is_live(self, email_hash: str) -> bool:
        """True while a code was issued for this email and has not expired or been used."""
        ...

    def discard(self, email_hash: str) -> None: ...
