"""user_sessions table: one row per signed-in device, with its current refresh token hash."""

from datetime import datetime
from uuid import UUID

from apps.accounts.domain.entities import Session
from apps.accounts.repositories.models import SessionModel


def _to_entity(row: SessionModel) -> Session:
    return Session(
        id=row.id,
        user_id=row.user_id,
        refresh_token_hash=row.refresh_token_hash,
        device_name=row.device_name,
        ip_address=row.ip_address,
        expires_at=row.expires_at,
        last_used_at=row.last_used_at,
        revoked_at=row.revoked_at,
        created_at=row.created_at,
    )


class PostgresSessionRepository:
    def create(
        self,
        *,
        session_id: UUID,
        user_id: UUID,
        refresh_token_hash: str,
        device_name: str | None,
        ip_address: str | None,
        expires_at: datetime,
    ) -> Session:
        row = SessionModel.objects.create(
            id=session_id,
            user_id=user_id,
            refresh_token_hash=refresh_token_hash,
            device_name=device_name,
            ip_address=ip_address,
            expires_at=expires_at,
        )
        return _to_entity(row)

    def get(self, session_id: UUID) -> Session | None:
        row = SessionModel.objects.filter(id=session_id).first()
        return _to_entity(row) if row else None

    def get_active(self, session_id: UUID, now: datetime) -> Session | None:
        row = SessionModel.objects.filter(
            id=session_id, revoked_at__isnull=True, expires_at__gt=now
        ).first()
        return _to_entity(row) if row else None

    def rotate(self, *, session_id: UUID, old_hash: str, new_hash: str, now: datetime) -> bool:
        # One conditional UPDATE: of two requests carrying the same old value, only one can win.
        changed = SessionModel.objects.filter(
            id=session_id, refresh_token_hash=old_hash, revoked_at__isnull=True, expires_at__gt=now
        ).update(refresh_token_hash=new_hash, last_used_at=now)
        return changed == 1

    def revoke(self, session_id: UUID, now: datetime) -> bool:
        return (
            SessionModel.objects.filter(id=session_id, revoked_at__isnull=True).update(
                revoked_at=now
            )
            == 1
        )

    def revoke_all(
        self, user_id: UUID, now: datetime, except_session_id: UUID | None = None
    ) -> int:
        sessions = SessionModel.objects.filter(user_id=user_id, revoked_at__isnull=True)
        if except_session_id is not None:
            sessions = sessions.exclude(id=except_session_id)
        return sessions.update(revoked_at=now)
