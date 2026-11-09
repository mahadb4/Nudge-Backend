"""Turns an Authorization header into the signed-in user and session, or refuses it."""

from apps.accounts.domain.entities import Principal
from apps.accounts.repositories.interfaces import SessionRepository
from common.constants import HeaderValue
from common.errors import Unauthorized
from common.interfaces import Clock, TokenSigner
from common.messages import Messages


class AuthenticationService:
    def __init__(self, signer: TokenSigner, sessions: SessionRepository, clock: Clock) -> None:
        self._signer = signer
        self._sessions = sessions
        self._clock = clock

    def authenticate(self, authorization: str | None) -> Principal:
        token = self._bearer_token(authorization)
        now = self._clock.now()
        claims = self._signer.verify_access(token, now=now)
        # One primary-key lookup per request: the token is only good while its session is.
        session = self._sessions.get_active(claims.session_id, now)
        if session is None or session.user_id != claims.user_id:
            raise Unauthorized(Messages.AUTH_ACCESS_TOKEN_INVALID)
        return Principal(user_id=claims.user_id, session_id=session.id)

    @staticmethod
    def _bearer_token(authorization: str | None) -> str:
        prefix = HeaderValue.BEARER_PREFIX
        if not authorization or not authorization.startswith(prefix):
            raise Unauthorized(Messages.AUTH_ACCESS_TOKEN_INVALID)
        token = authorization[len(prefix) :]
        if not token or " " in token:
            raise Unauthorized(Messages.AUTH_ACCESS_TOKEN_INVALID)
        return token
