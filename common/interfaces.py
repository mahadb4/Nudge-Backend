"""Protocols for infrastructure (ARCHITECTURE 2, 5). Services depend on these, never on
implementations.

Framework-free. Implementations live in common/infra and common/security; fakes in
common/tests/fakes.py.
"""

from collections.abc import Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol
from uuid import UUID

from common.constants import ActorType, AuditAction, EmailKind


class Clock(Protocol):
    def now(self) -> datetime:
        """Timezone-aware UTC."""
        ...


class Cache(Protocol):
    def get(self, key: str) -> str | None: ...

    def set(self, key: str, value: str, ttl_seconds: int) -> None: ...

    def add(self, key: str, value: str, ttl_seconds: int) -> bool:
        """Set only if absent (atomic). True when it was set."""
        ...

    def incr(self, key: str, ttl_seconds: int) -> int:
        """Atomic +1. Creates the key at 1 with ttl_seconds when absent; never extends an existing
        TTL."""
        ...

    def delete(self, key: str) -> None: ...


@dataclass(frozen=True, slots=True)
class EmailMessage:
    """text_body is always the full message. A message with a kind also gets an HTML version
    (html_body) from the renderer; the kind's values are only inserted into its template."""

    to: str
    subject: str
    text_body: str
    kind: EmailKind | None = None
    recipient_name: str | None = None
    code: str | None = None
    link: str | None = None
    html_body: str | None = None


class EmailSender(Protocol):
    def send(self, message: EmailMessage) -> None: ...


@dataclass(frozen=True, slots=True)
class AuditEvent:
    action: AuditAction
    actor_type: ActorType
    actor_id: UUID | None
    organization_id: UUID | None
    object_type: str | None = None
    object_id: UUID | None = None
    details: Mapping[str, object] = field(default_factory=dict)
    ip_address: str | None = None


class AuditWriter(Protocol):
    def write(self, event: AuditEvent) -> None: ...


class PasswordHasher(Protocol):
    def hash(self, raw: str) -> str: ...

    def verify(self, raw: str, encoded: str) -> bool: ...

    def needs_rehash(self, encoded: str) -> bool: ...

    def dummy_verify(self, raw: str) -> None:
        """Same cost as verify(); used for unknown emails so timing reveals nothing."""
        ...


@dataclass(frozen=True, slots=True)
class IssuedToken:
    token: str
    jti: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class AccessClaims:
    user_id: UUID
    session_id: UUID
    jti: str
    expires_at: datetime


class TokenSigner(Protocol):
    def issue_access(self, *, user_id: UUID, session_id: UUID, now: datetime) -> IssuedToken: ...

    def verify_access(self, token: str, *, now: datetime) -> AccessClaims:
        """Raises Unauthorized(Messages.AUTH_ACCESS_TOKEN_INVALID) for any bad, expired or tampered
        token."""
        ...


class IdGenerator(Protocol):
    def new_id(self) -> UUID:
        """A new UUIDv7. Time-ordered, so new rows append to the end of the primary key index."""
        ...


class UnitOfWork(Protocol):
    def atomic(self) -> AbstractContextManager[None]:
        """One database transaction. Everything inside commits together or not at all. Nests as
        savepoints."""
        ...


class Hasher(Protocol):
    def digest(self, namespace: str, value: str) -> str:
        """Keyed HMAC-SHA256 as 64 hex characters. Used for emails and codes in cache keys and audit
        rows."""
        ...
