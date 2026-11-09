"""Keyed hashing for values that must never be stored or logged in the clear (emails, verification
codes)."""

import hashlib
import hmac


class HmacHasher:
    def __init__(self, key: str) -> None:
        self._key = key.encode("utf-8")

    def digest(self, namespace: str, value: str) -> str:
        return hmac.new(self._key, f"{namespace}:{value}".encode(), hashlib.sha256).hexdigest()
