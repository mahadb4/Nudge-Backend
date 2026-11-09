from datetime import UTC, datetime, timedelta, timezone

import pytest

from common.infra.clock import FrozenClock, SystemClock
from common.tests.fakes import FakeCache, FakePasswordHasher

START = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)


def test_system_clock_is_aware_utc():
    now = SystemClock().now()
    assert now.tzinfo is not None and now.utcoffset() == timedelta(0)


def test_frozen_clock_moves_only_on_advance():
    clock = FrozenClock(START)
    assert clock.now() == START
    clock.advance(30)
    assert clock.now() == START + timedelta(seconds=30)


def test_frozen_clock_converts_to_utc_and_refuses_naive():
    karachi = timezone(timedelta(hours=5))
    assert FrozenClock(datetime(2026, 11, 9, 17, 0, tzinfo=karachi)).now() == START
    with pytest.raises(ValueError):
        FrozenClock(datetime(2026, 11, 9))


def test_fake_cache_expiry_add_and_incr():
    clock = FrozenClock(START)
    cache = FakeCache(clock)
    assert cache.add("k", "a", 10) is True
    assert cache.add("k", "b", 10) is False
    assert cache.get("k") == "a"
    clock.advance(10)
    assert cache.get("k") is None
    assert cache.incr("n", 5) == 1 and cache.incr("n", 5) == 2
    clock.advance(5)
    assert cache.incr("n", 5) == 1  # window over, counter restarts


def test_fake_hasher():
    hasher = FakePasswordHasher()
    encoded = hasher.hash("Secret-1x")
    assert hasher.verify("Secret-1x", encoded) and not hasher.verify("other", encoded)
    hasher.dummy_verify("x")
    assert hasher.dummy_calls == 1
