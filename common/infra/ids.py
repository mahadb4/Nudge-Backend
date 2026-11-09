"""UUIDv7 ids (RFC 9562): 48-bit millisecond timestamp + random bits, so new rows append to the end
of the index."""

import os
from uuid import UUID

from common.interfaces import Clock

TIMESTAMP_BYTES = 6
RANDOM_BYTES = 10
VERSION_7 = 0x70
VARIANT_RFC = 0x80


class UuidV7Generator:
    def __init__(self, clock: Clock) -> None:
        self._clock = clock

    def new_id(self) -> UUID:
        millis = int(self._clock.now().timestamp() * 1000)
        raw = bytearray(millis.to_bytes(TIMESTAMP_BYTES, "big") + os.urandom(RANDOM_BYTES))
        raw[6] = (raw[6] & 0x0F) | VERSION_7
        raw[8] = (raw[8] & 0x3F) | VARIANT_RFC
        return UUID(bytes=bytes(raw))
