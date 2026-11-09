"""What the health service needs from the database. The service depends on this Protocol, not on
SQL."""

from typing import Protocol


class HealthRepository(Protocol):
    def is_database_available(self) -> bool:
        """True when the database answers and the schema is present. Never raises."""
        ...
