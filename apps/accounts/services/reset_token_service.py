"""Password reset tokens: '<user id>-<expiry>-<signature>', valid for an hour, usable once.

The signature covers the user's current password hash and last sign-in time. Setting a new password
or signing in changes them, so every open link stops working (that is what makes it single use)
without a table of used tokens. The token holds no email and nothing secret.
"""

import hmac
import re
from datetime import timedelta
from uuid import UUID

from apps.accounts.domain.entities import User
from common.constants import HmacNamespace, Ttl
from common.interfaces import Clock, Hasher

_FORMAT = re.compile(r"([0-9a-f]{32})-([0-9]{1,12})-([0-9a-f]{64})")


class ResetTokenService:
    def __init__(self, digests: Hasher, clock: Clock) -> None:
        self._digests = digests
        self._clock = clock

    def issue(self, user: User) -> str:
        expires_at = int((self._clock.now() + timedelta(seconds=Ttl.RESET_LINK)).timestamp())
        return f"{user.id.hex}-{expires_at}-{self._signature(user, expires_at)}"

    def user_id_in(self, token: object) -> UUID | None:
        """Who the token claims to be for. Not proof of anything until is_valid() agrees."""
        parts = _split(token)
        return UUID(hex=parts[0]) if parts else None

    def is_valid(self, token: object, user: User) -> bool:
        parts = _split(token)
        if parts is None or parts[0] != user.id.hex:
            return False
        _, expires_at, signature = parts
        if int(expires_at) <= int(self._clock.now().timestamp()):
            return False
        return hmac.compare_digest(signature, self._signature(user, int(expires_at)))

    def _signature(self, user: User, expires_at: int) -> str:
        last_login = user.last_login.isoformat() if user.last_login else ""
        return self._digests.digest(
            HmacNamespace.RESET_TOKEN,
            f"{user.id.hex}|{expires_at}|{user.password_hash}|{last_login}",
        )


def _split(token: object) -> tuple[str, str, str] | None:
    match = _FORMAT.fullmatch(token) if isinstance(token, str) else None
    return (match.group(1), match.group(2), match.group(3)) if match else None
