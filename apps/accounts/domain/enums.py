"""Enums owned by accounts. Role and AccountType are shared across modules, so they live in
common/constants.py."""

from enum import Enum, IntEnum


class MembershipStatus(IntEnum):
    ACTIVE = 1
    SUSPENDED = 2
    REMOVED = 3  # the row is kept so ownership history stays valid


class CodeCheck(Enum):
    OK = "ok"
    WRONG = "wrong"  # also covers "no code at all", so a client cannot tell the two apart
    LOCKED = "locked"  # too many wrong tries; a new code is needed
