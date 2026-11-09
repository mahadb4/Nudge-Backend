"""Enums owned by crm."""

from enum import IntEnum


class StageOutcome(IntEnum):
    OPEN = 1
    WON = 2
    LOST = 3
