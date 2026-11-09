"""Refresh token values: '<session uuid>.<256-bit secret>'. Only sha256 of the whole value is ever
stored.

The session id in front lets the server find the session even for a value that was already rotated,
which is
how reuse of an old value (theft) is detected.
"""

import hashlib
import re
import secrets
from uuid import UUID

SECRET_BYTES = 32
_FORMAT = re.compile(
    r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\.([A-Za-z0-9_-]{43})"
)


def new_refresh_value(session_id: UUID) -> str:
    return f"{session_id}.{secrets.token_urlsafe(SECRET_BYTES)}"


def split_refresh_value(value: str) -> UUID | None:
    """The session id inside a well-formed value, or None for anything else."""
    match = _FORMAT.fullmatch(value)
    return UUID(match.group(1)) if match else None


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
