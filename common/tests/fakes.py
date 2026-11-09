"""In-memory fakes of the Protocols in common/interfaces.py, for service unit tests (no database, no
HTTP)."""

from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from uuid import UUID

from common.infra.clock import FrozenClock
from common.interfaces import AuditEvent, Clock, EmailMessage


class FakeCache:
    """Expiry follows the injected clock, so tests can move time forward."""

    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._items: dict[str, tuple[str, float]] = {}

    def _alive(self, key: str) -> tuple[str, float] | None:
        item = self._items.get(key)
        if item is None:
            return None
        if item[1] <= self._clock.now().timestamp():
            del self._items[key]
            return None
        return item

    def get(self, key: str) -> str | None:
        item = self._alive(key)
        return item[0] if item else None

    def set(self, key: str, value: str, ttl_seconds: int) -> None:
        self._items[key] = (value, self._clock.now().timestamp() + ttl_seconds)

    def add(self, key: str, value: str, ttl_seconds: int) -> bool:
        if self._alive(key):
            return False
        self.set(key, value, ttl_seconds)
        return True

    def incr(self, key: str, ttl_seconds: int) -> int:
        item = self._alive(key)
        if item is None:
            self.set(key, "1", ttl_seconds)
            return 1
        value = int(item[0]) + 1
        self._items[key] = (str(value), item[1])
        return value

    def delete(self, key: str) -> None:
        self._items.pop(key, None)


class FakeEmailSender:
    def __init__(self) -> None:
        self.outbox: list[EmailMessage] = []

    def send(self, message: EmailMessage) -> None:
        self.outbox.append(message)


class FakeAuditWriter:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    def write(self, event: AuditEvent) -> None:
        self.events.append(event)

    def actions(self) -> list[str]:
        return [str(event.action) for event in self.events]


class FakePasswordHasher:
    """Fast and readable; never use outside tests."""

    PREFIX = "fake$"

    def __init__(self) -> None:
        self.dummy_calls = 0

    def hash(self, raw: str) -> str:
        return self.PREFIX + raw[::-1]

    def verify(self, raw: str, encoded: str) -> bool:
        return encoded == self.hash(raw)

    def needs_rehash(self, encoded: str) -> bool:
        return not encoded.startswith(self.PREFIX)

    def dummy_verify(self, raw: str) -> None:
        self.dummy_calls += 1


class SequentialIdGenerator:
    """UUID(int=1), UUID(int=2), ...: readable ids in test failures."""

    def __init__(self) -> None:
        self._next = 0

    def new_id(self) -> UUID:
        self._next += 1
        return UUID(int=self._next)


class FakeUnitOfWork:
    """Counts how many transactions were opened and how many ended with an error (nothing is rolled
    back)."""

    def __init__(self) -> None:
        self.opened = 0
        self.failed = 0

    def atomic(self) -> AbstractContextManager[None]:
        return self._atomic()

    @contextmanager
    def _atomic(self) -> Iterator[None]:
        self.opened += 1
        try:
            yield
        except BaseException:
            self.failed += 1
            raise


__all__ = [
    "FakeAuditWriter",
    "FakeCache",
    "FakeEmailSender",
    "FakePasswordHasher",
    "FakeUnitOfWork",
    "FrozenClock",
    "SequentialIdGenerator",
]
