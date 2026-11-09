"""Access tokens: HS256 JWT with user_id, sid (the session), jti, iat and exp.

Expiry is checked against the injected clock (not the machine clock), so tests can move time.
"""

import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt

from common.constants import JWT_ALGORITHM, TokenClaim, Ttl
from common.errors import Unauthorized
from common.interfaces import AccessClaims, IssuedToken
from common.messages import Messages

JTI_BYTES = 16
REQUIRED_CLAIMS = [
    TokenClaim.USER_ID,
    TokenClaim.SESSION_ID,
    TokenClaim.JTI,
    TokenClaim.ISSUED_AT,
    TokenClaim.EXPIRES_AT,
]


class JwtTokenSigner:
    def __init__(self, signing_key: str) -> None:
        self._key = signing_key

    def issue_access(self, *, user_id: UUID, session_id: UUID, now: datetime) -> IssuedToken:
        expires_at = now + timedelta(seconds=Ttl.ACCESS_TOKEN)
        jti = secrets.token_hex(JTI_BYTES)
        payload = {
            TokenClaim.USER_ID: str(user_id),
            TokenClaim.SESSION_ID: str(session_id),
            TokenClaim.JTI: jti,
            TokenClaim.ISSUED_AT: int(now.timestamp()),
            TokenClaim.EXPIRES_AT: int(expires_at.timestamp()),
        }
        return IssuedToken(jwt.encode(payload, self._key, algorithm=JWT_ALGORITHM), jti, expires_at)

    def verify_access(self, token: str, *, now: datetime) -> AccessClaims:
        try:
            claims = jwt.decode(
                token,
                self._key,
                # A token that says alg=none or another algorithm is refused.
                algorithms=[JWT_ALGORITHM],
                options={"require": REQUIRED_CLAIMS, "verify_exp": False, "verify_iat": False},
            )
            expires_at = datetime.fromtimestamp(int(claims[TokenClaim.EXPIRES_AT]), UTC)
            user_id = UUID(claims[TokenClaim.USER_ID])
            session_id = UUID(claims[TokenClaim.SESSION_ID])
        except (jwt.PyJWTError, ValueError, TypeError, OverflowError) as exc:
            raise Unauthorized(Messages.AUTH_ACCESS_TOKEN_INVALID) from exc
        if expires_at <= now:
            raise Unauthorized(Messages.AUTH_ACCESS_TOKEN_INVALID)
        return AccessClaims(user_id, session_id, str(claims[TokenClaim.JTI]), expires_at)
