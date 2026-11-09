"""The Cache Protocol on top of Django's cache framework (Redis in production, local memory in
development)."""

from collections.abc import Callable
from typing import TypeVar

from django.core.cache.backends.base import BaseCache
from redis.exceptions import RedisError

from common.errors import ServiceUnavailable

T = TypeVar("T")


class DjangoCache:
    """Any cache failure becomes ServiceUnavailable, so callers fail closed (CODING_STYLE 7)."""

    def __init__(self, backend: BaseCache) -> None:
        self._backend = backend

    def get(self, key: str) -> str | None:
        value = self._call(self._backend.get, key)
        return None if value is None else str(value)

    def set(self, key: str, value: str, ttl_seconds: int) -> None:
        self._call(self._backend.set, key, value, ttl_seconds)

    def add(self, key: str, value: str, ttl_seconds: int) -> bool:
        return bool(self._call(self._backend.add, key, value, ttl_seconds))

    def incr(self, key: str, ttl_seconds: int) -> int:
        # add() creates the key with its TTL, incr() never changes a TTL. Two tries cover a key that
        # expires in between.
        for _ in range(2):
            if self._call(self._backend.add, key, 1, ttl_seconds):
                return 1
            try:
                return int(self._call(self._backend.incr, key))
            except ValueError:
                continue
        return int(self._call(self._backend.incr, key))

    def delete(self, key: str) -> None:
        self._call(self._backend.delete, key)

    @staticmethod
    def _call(operation: Callable[..., T], *args: object) -> T:
        try:
            return operation(*args)
        except (RedisError, OSError) as exc:
            raise ServiceUnavailable() from exc
