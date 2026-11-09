"""Password hashing with Argon2 in Django's hash format (argon2$argon2id$...), about 100 characters,
fits users.password."""

from functools import cached_property

from django.contrib.auth.hashers import check_password, identify_hasher, make_password

ALGORITHM = "argon2"
DUMMY_PASSWORD = "not-a-real-password-used-only-for-timing"


class Argon2PasswordHasher:
    def hash(self, raw: str) -> str:
        return make_password(raw, hasher=ALGORITHM)

    def verify(self, raw: str, encoded: str) -> bool:
        return check_password(raw, encoded)

    def needs_rehash(self, encoded: str) -> bool:
        return identify_hasher(encoded).must_update(encoded)

    def dummy_verify(self, raw: str) -> None:
        """Costs the same as verify(), so an unknown email cannot be told apart by timing."""
        check_password(raw, self._dummy_hash)

    @cached_property
    def _dummy_hash(self) -> str:
        return self.hash(DUMMY_PASSWORD)
