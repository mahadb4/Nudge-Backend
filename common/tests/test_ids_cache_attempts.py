"""Ids, the cache adapter and the attempt limiter."""

from datetime import UTC, datetime

import pytest
from django.core.cache import caches
from redis.exceptions import ConnectionError as RedisConnectionError

from common.attempts import AttemptLimiter
from common.constants import AttemptLimit, AttemptLimits, attempt_key
from common.errors import RateLimited, ServiceUnavailable
from common.infra.cache import DjangoCache
from common.infra.clock import FrozenClock
from common.infra.ids import UuidV7Generator
from common.tests.fakes import FakeCache

START = datetime(
    2026, 11, 9, 12, 0, 0, tzinfo=UTC
)  # a multiple of 60 seconds, so windows start here


# ---- ids


def test_ids_are_uuid_v7():
    generator = UuidV7Generator(FrozenClock(START))
    value = generator.new_id()
    assert value.version == 7
    assert value.variant == "specified in RFC 4122"


def test_ids_are_unique_and_sort_by_time():
    clock = FrozenClock(START)
    generator = UuidV7Generator(clock)
    first = [generator.new_id() for _ in range(50)]
    assert len(set(first)) == 50
    clock.advance(0.01)
    later = generator.new_id()
    assert later > max(first)  # a later millisecond always sorts after
    assert later.int >> 80 == int(
        clock.now().timestamp() * 1000
    )  # the first 48 bits are the timestamp


# ---- cache adapter on Django's local memory cache


@pytest.fixture
def adapter() -> DjangoCache:
    backend = caches["default"]
    backend.clear()
    return DjangoCache(backend)


def test_cache_get_set_delete(adapter):
    assert adapter.get("a") is None
    adapter.set("a", "1", 60)
    assert adapter.get("a") == "1"
    adapter.delete("a")
    assert adapter.get("a") is None


def test_cache_values_come_back_as_text(adapter):
    adapter.incr("n", 60)
    assert adapter.get("n") == "1"


def test_cache_add_only_sets_when_absent(adapter):
    assert adapter.add("k", "first", 60) is True
    assert adapter.add("k", "second", 60) is False
    assert adapter.get("k") == "first"


def test_cache_incr_counts_from_one(adapter):
    assert [adapter.incr("c", 60) for _ in range(3)] == [1, 2, 3]


class BrokenBackend:
    def get(self, *args):
        raise RedisConnectionError("down")

    set = add = incr = delete = get


@pytest.mark.parametrize("operation", ["get", "delete"])
def test_a_cache_failure_becomes_service_unavailable(operation):
    broken = DjangoCache(BrokenBackend())
    with pytest.raises(ServiceUnavailable):
        getattr(broken, operation)("k")


def test_a_cache_failure_on_write_and_incr_becomes_service_unavailable():
    broken = DjangoCache(BrokenBackend())
    with pytest.raises(ServiceUnavailable):
        broken.set("k", "v", 1)
    with pytest.raises(ServiceUnavailable):
        broken.add("k", "v", 1)
    with pytest.raises(ServiceUnavailable):
        broken.incr("k", 1)


# ---- attempt limiter

LIMIT = AttemptLimit("test_limit", 5, 60)


@pytest.fixture
def clock() -> FrozenClock:
    return FrozenClock(START)


@pytest.fixture
def limiter(clock) -> AttemptLimiter:
    return AttemptLimiter(FakeCache(clock), clock)


def test_attempts_up_to_the_limit_are_allowed(limiter):
    for _ in range(LIMIT.max_attempts):
        limiter.hit(LIMIT, "ip:1")


def test_the_next_attempt_is_refused_with_retry_after(limiter, clock):
    for _ in range(LIMIT.max_attempts):
        limiter.hit(LIMIT, "ip:1")
    clock.advance(10)
    with pytest.raises(RateLimited) as info:
        limiter.hit(LIMIT, "ip:1")
    assert info.value.code == "COMMON_RATE_LIMITED"
    assert info.value.headers == {"Retry-After": "50"}


def test_subjects_are_counted_separately(limiter):
    for _ in range(LIMIT.max_attempts):
        limiter.hit(LIMIT, "ip:1")
    limiter.hit(LIMIT, "ip:2")


def test_the_limit_resets_in_the_next_window(limiter, clock):
    for _ in range(LIMIT.max_attempts):
        limiter.hit(LIMIT, "ip:1")
    clock.advance(60)
    limiter.hit(LIMIT, "ip:1")


def test_reset_clears_the_counter(limiter):
    for _ in range(LIMIT.max_attempts):
        limiter.hit(LIMIT, "ip:1")
    limiter.reset(LIMIT, "ip:1")
    limiter.hit(LIMIT, "ip:1")


def test_the_resend_limit_is_one_per_30_seconds(limiter, clock):
    limiter.hit(AttemptLimits.RESEND_EMAIL, "email:x")
    with pytest.raises(RateLimited):
        limiter.hit(AttemptLimits.RESEND_EMAIL, "email:x")
    clock.advance(30)
    limiter.hit(AttemptLimits.RESEND_EMAIL, "email:x")


def test_a_cache_failure_refuses_the_request(clock):
    limiter = AttemptLimiter(DjangoCache(BrokenBackend()), clock)
    with pytest.raises(ServiceUnavailable):
        limiter.hit(LIMIT, "ip:1")


def test_counters_live_in_the_cache_not_in_memory(clock):
    cache = FakeCache(clock)
    AttemptLimiter(cache, clock).hit(LIMIT, "ip:1")
    # A second limiter (another API copy) sharing the cache sees the same count.
    other = AttemptLimiter(cache, clock)
    for _ in range(LIMIT.max_attempts - 1):
        other.hit(LIMIT, "ip:1")
    with pytest.raises(RateLimited):
        other.hit(LIMIT, "ip:1")
    assert cache.get(attempt_key(LIMIT, "ip:1", int(START.timestamp()) // 60)) == "6"
