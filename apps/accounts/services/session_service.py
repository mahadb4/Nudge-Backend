"""Sessions: one per signed-in device. Creates the refresh value (stored only as a hash), rotates
it, and detects reuse of an old value."""

import hmac
from datetime import datetime, timedelta
from uuid import UUID

from apps.accounts.domain.entities import Rotation, Session, SessionTokens
from apps.accounts.repositories.interfaces import SessionRepository, UserRepository
from common.constants import ActorType, AuditAction, Ttl
from common.errors import Unauthorized
from common.interfaces import AuditEvent, AuditWriter, Clock, IdGenerator, TokenSigner, UnitOfWork
from common.messages import Messages
from common.security.refresh_tokens import new_refresh_value, sha256_hex, split_refresh_value

AUDIT_OBJECT_SESSION = "session"


class SessionService:
    def __init__(
        self,
        *,
        sessions: SessionRepository,
        users: UserRepository,
        signer: TokenSigner,
        ids: IdGenerator,
        clock: Clock,
        audit: AuditWriter,
        uow: UnitOfWork,
    ) -> None:
        self._sessions = sessions
        self._users = users
        self._signer = signer
        self._ids = ids
        self._clock = clock
        self._audit = audit
        self._uow = uow

    def start(
        self, *, user_id: UUID, remember: bool, ip_address: str | None, device_name: str | None
    ) -> SessionTokens:
        now = self._clock.now()
        session_id = self._ids.new_id()
        refresh_value = new_refresh_value(session_id)
        lifetime = Ttl.REFRESH_REMEMBER if remember else Ttl.REFRESH_SESSION
        self._sessions.create(
            session_id=session_id,
            user_id=user_id,
            refresh_token_hash=sha256_hex(refresh_value),
            device_name=device_name,
            ip_address=ip_address,
            expires_at=now + timedelta(seconds=lifetime),
        )
        access = self._signer.issue_access(user_id=user_id, session_id=session_id, now=now)
        return SessionTokens(
            access_token=access.token,
            refresh_value=refresh_value,
            cookie_max_age=Ttl.REFRESH_REMEMBER if remember else None,
        )

    def refresh(self, value: object, ip_address: str | None) -> Rotation:
        """Swap the refresh value for a new one. Any problem is the same 401, and a value that is
        not the session's current one burns the whole session (theft, or two requests at once)."""
        now = self._clock.now()
        if not isinstance(value, str):
            raise Unauthorized(Messages.AUTH_SESSION_INVALID)
        session = self._find_live_session(value, now)
        presented = sha256_hex(value)
        if not hmac.compare_digest(presented, session.refresh_token_hash):
            self._burn(session, ip_address)
            raise Unauthorized(Messages.AUTH_SESSION_INVALID)
        user = self._users.get(session.user_id)
        if user is None or not user.is_active or user.email_verified_at is None:
            self._sessions.revoke(session.id, now)
            raise Unauthorized(Messages.AUTH_SESSION_INVALID)

        new_value = new_refresh_value(session.id)
        # One conditional UPDATE: of two requests with the same value only one can win.
        if not self._sessions.rotate(
            session_id=session.id, old_hash=presented, new_hash=sha256_hex(new_value), now=now
        ):
            self._burn(session, ip_address)
            raise Unauthorized(Messages.AUTH_SESSION_INVALID)
        access = self._signer.issue_access(user_id=session.user_id, session_id=session.id, now=now)
        return Rotation(
            user_id=session.user_id,
            tokens=SessionTokens(
                access_token=access.token,
                refresh_value=new_value,
                cookie_max_age=_cookie_max_age(session, now),
            ),
        )

    def end(self, value: object) -> Session | None:
        """Log out one device. Only the session's current value can do it; anything else does
        nothing."""
        now = self._clock.now()
        session_id = split_refresh_value(value) if isinstance(value, str) else None
        session = self._sessions.get(session_id) if session_id else None
        if session is None or not isinstance(value, str):
            return None
        if not hmac.compare_digest(sha256_hex(value), session.refresh_token_hash):
            return None
        return session if self._sessions.revoke(session.id, now) else None

    def revoke_others(self, user_id: UUID, keep_session_id: UUID) -> int:
        return self._sessions.revoke_all(user_id, self._clock.now(), keep_session_id)

    def revoke_all(self, user_id: UUID) -> int:
        return self._sessions.revoke_all(user_id, self._clock.now())

    def _find_live_session(self, value: str, now: datetime) -> Session:
        session_id = split_refresh_value(value)
        session = self._sessions.get(session_id) if session_id else None
        if session is None or session.revoked_at is not None or session.expires_at <= now:
            raise Unauthorized(Messages.AUTH_SESSION_INVALID)
        return session

    def _burn(self, session: Session, ip_address: str | None) -> None:
        with self._uow.atomic():
            self._sessions.revoke(session.id, self._clock.now())
            self._audit.write(
                AuditEvent(
                    action=AuditAction.SESSION_REUSE_DETECTED,
                    actor_type=ActorType.USER,
                    actor_id=session.user_id,
                    organization_id=None,
                    object_type=AUDIT_OBJECT_SESSION,
                    object_id=session.id,
                    ip_address=ip_address,
                )
            )


def _cookie_max_age(session: Session, now: datetime) -> int | None:
    """A 'keep me signed in' session keeps a persistent cookie for the time it has left."""
    lifetime = session.expires_at - session.created_at
    if lifetime < timedelta(seconds=Ttl.REMEMBER_MIN_LIFETIME):
        return None
    return max(1, int((session.expires_at - now).total_seconds()))
