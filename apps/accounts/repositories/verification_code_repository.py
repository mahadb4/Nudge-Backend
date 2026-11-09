"""Verification codes in the shared cache: 6 digits, 10 minutes, 5 wrong tries. No table.

Only an HMAC of the code is stored. Everything is keyed by the HMAC of the email, so an unknown
email behaves
exactly like a known one (same tries counter, same lock), which stops the endpoint from revealing
accounts.
"""

import hmac
import secrets

from apps.accounts.domain.enums import CodeCheck
from common.constants import AuthRules, HmacNamespace, Ttl, verify_code_key, verify_tries_key
from common.interfaces import Cache, Hasher


class CacheVerificationCodeRepository:
    def __init__(self, cache: Cache, digests: Hasher) -> None:
        self._cache = cache
        self._digests = digests

    def issue(self, email_hash: str) -> str:
        code = f"{secrets.randbelow(10**AuthRules.CODE_LENGTH):0{AuthRules.CODE_LENGTH}d}"
        self._cache.set(
            verify_code_key(email_hash), self._digest(email_hash, code), Ttl.VERIFY_CODE
        )
        self._cache.delete(verify_tries_key(email_hash))
        return code

    def check(self, email_hash: str, code: str) -> CodeCheck:
        if int(self._cache.get(verify_tries_key(email_hash)) or 0) >= AuthRules.CODE_MAX_TRIES:
            return CodeCheck.LOCKED
        stored = self._cache.get(verify_code_key(email_hash))
        if stored is not None and hmac.compare_digest(stored, self._digest(email_hash, code)):
            return CodeCheck.OK
        self._cache.incr(verify_tries_key(email_hash), Ttl.VERIFY_CODE)
        return CodeCheck.WRONG

    def discard(self, email_hash: str) -> None:
        self._cache.delete(verify_code_key(email_hash))
        self._cache.delete(verify_tries_key(email_hash))

    def _digest(self, email_hash: str, code: str) -> str:
        return self._digests.digest(HmacNamespace.VERIFY_CODE, f"{email_hash}:{code}")
