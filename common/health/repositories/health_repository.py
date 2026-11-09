"""The only health code that touches the database. Read-only."""

import logging

from django.db import DatabaseError, connections, transaction

logger = logging.getLogger(__name__)

STATEMENT_TIMEOUT_MS = 2000


class PostgresHealthRepository:
    def __init__(self, alias: str = "default") -> None:
        self._alias = alias

    def is_database_available(self) -> bool:
        try:
            with transaction.atomic(using=self._alias), connections[self._alias].cursor() as cursor:
                cursor.execute("SET LOCAL statement_timeout = %s", [STATEMENT_TIMEOUT_MS])
                cursor.execute("SELECT 1")
                cursor.execute("SELECT 1 FROM users LIMIT 1")
            return True
        except DatabaseError as exc:
            # Class name only: the message can contain the host or user.
            logger.warning("Health check failed: %s", type(exc).__name__)
            return False
