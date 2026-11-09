"""Users table. Returns User entities, never ORM rows."""

from collections.abc import Mapping
from datetime import datetime
from uuid import UUID

from django.db import IntegrityError, transaction
from django.db.models.functions import Now

from apps.accounts.domain.entities import User
from apps.accounts.domain.errors import DuplicateEmail
from apps.accounts.repositories.models import UserModel

UNIQUE_EMAIL_INDEX = "uq_users_1"
# The only user columns a profile update may touch (entity field -> column).
PROFILE_COLUMNS = {
    "full_name": "full_name",
    "phone": "phone",
    "timezone": "timezone",
    "quiet_hours_start": "quiet_hours_start",
    "quiet_hours_end": "quiet_hours_end",
}


def _to_entity(row: UserModel) -> User:
    return User(
        id=row.id,
        email=row.email,
        password_hash=row.password,
        full_name=row.full_name,
        phone=row.phone,
        timezone=row.timezone,
        is_active=row.is_active,
        email_verified_at=row.email_verified_at,
        last_login=row.last_login,
        created_at=row.created_at,
        quiet_hours_start=row.quiet_hours_start,
        quiet_hours_end=row.quiet_hours_end,
    )


def _is_duplicate_email(error: IntegrityError) -> bool:
    diag = getattr(error.__cause__, "diag", None)
    return getattr(diag, "constraint_name", None) == UNIQUE_EMAIL_INDEX


class PostgresUserRepository:
    def get(self, user_id: UUID) -> User | None:
        row = UserModel.objects.filter(id=user_id).first()
        return _to_entity(row) if row else None

    def get_by_email(self, email: str) -> User | None:
        row = UserModel.objects.filter(email=email).first()
        return _to_entity(row) if row else None

    def email_exists(self, email: str) -> bool:
        return UserModel.objects.filter(email=email).exists()

    def create(
        self, *, user_id: UUID, email: str, password_hash: str, full_name: str, timezone: str
    ) -> User:
        try:
            # The inner transaction is a savepoint: a duplicate does not poison the caller's
            # transaction.
            with transaction.atomic():
                row = UserModel.objects.create(
                    id=user_id,
                    email=email,
                    password=password_hash,
                    full_name=full_name,
                    timezone=timezone,
                )
        except IntegrityError as exc:
            if _is_duplicate_email(exc):
                raise DuplicateEmail() from exc
            raise
        return _to_entity(row)

    def replace_registration(
        self, *, user_id: UUID, password_hash: str, full_name: str, timezone: str
    ) -> bool:
        # The email_verified_at filter makes this safe against a verification that lands first.
        changed = UserModel.objects.filter(id=user_id, email_verified_at__isnull=True).update(
            password=password_hash, full_name=full_name, timezone=timezone, updated_at=Now()
        )
        return changed == 1

    def mark_email_verified(self, user_id: UUID, at: datetime) -> bool:
        changed = UserModel.objects.filter(id=user_id, email_verified_at__isnull=True).update(
            email_verified_at=at, updated_at=Now()
        )
        return changed == 1

    def set_password(self, user_id: UUID, password_hash: str) -> None:
        UserModel.objects.filter(id=user_id).update(password=password_hash, updated_at=Now())

    def update_profile(self, user_id: UUID, changes: Mapping[str, object]) -> User | None:
        columns = {PROFILE_COLUMNS[name]: value for name, value in changes.items()}
        UserModel.objects.filter(id=user_id).update(**columns, updated_at=Now())
        return self.get(user_id)

    def change_password(self, *, user_id: UUID, expected_hash: str, new_hash: str) -> bool:
        changed = UserModel.objects.filter(id=user_id, password=expected_hash).update(
            password=new_hash, updated_at=Now()
        )
        return changed == 1

    def touch_last_login(self, user_id: UUID, at: datetime) -> None:
        UserModel.objects.filter(id=user_id).update(last_login=at)
