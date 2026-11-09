"""A simple fixed-window attempt limit for the midterm (the full token bucket comes after it).

Counters live in the shared Cache, never in process memory, so any number of API copies agree
(CODING_STYLE 7).
The cache fails closed: if it is down, the call raises ServiceUnavailable and the request is
refused.
Known weakness of fixed windows: a burst across a window boundary can reach twice the limit.
"""

import math

from common.constants import AttemptLimit, attempt_key
from common.errors import RateLimited
from common.interfaces import Cache, Clock


class AttemptLimiter:
    def __init__(self, cache: Cache, clock: Clock) -> None:
        self._cache = cache
        self._clock = clock

    def hit(self, limit: AttemptLimit, subject: str) -> None:
        """Count one attempt. Raises RateLimited (with Retry-After) once the window's limit is
        passed."""
        now = self._clock.now().timestamp()
        window_index = int(now) // limit.window_seconds
        count = self._cache.incr(attempt_key(limit, subject, window_index), limit.window_seconds)
        if count > limit.max_attempts:
            raise RateLimited(
                retry_after=math.ceil((window_index + 1) * limit.window_seconds - now)
            )

    def reset(self, limit: AttemptLimit, subject: str) -> None:
        window_index = int(self._clock.now().timestamp()) // limit.window_seconds
        self._cache.delete(attempt_key(limit, subject, window_index))
