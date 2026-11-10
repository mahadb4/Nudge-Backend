"""Enums owned by crm."""

from enum import IntEnum
from types import MappingProxyType


class StageOutcome(IntEnum):
    OPEN = 1
    WON = 2
    LOST = 3


class Visibility(IntEnum):
    PRIVATE = 1
    TEAM = 2
    ORGANIZATION = 3


class CompanySize(IntEnum):
    """companies.size_range: 1-10, 11-50, 51-200, 201-500, 500+."""

    S1_10 = 1
    S11_50 = 2
    S51_200 = 3
    S201_500 = 4
    S500_PLUS = 5


# What the API says for each code (API_CONTRACT: smallint codes are lowercase strings).
VISIBILITY_WIRE = MappingProxyType(
    {
        Visibility.PRIVATE: "private",
        Visibility.TEAM: "team",
        Visibility.ORGANIZATION: "organization",
    }
)
COMPANY_SIZE_WIRE = MappingProxyType(
    {
        CompanySize.S1_10: "1-10",
        CompanySize.S11_50: "11-50",
        CompanySize.S51_200: "51-200",
        CompanySize.S201_500: "201-500",
        CompanySize.S500_PLUS: "500+",
    }
)
VISIBILITY_BY_WIRE = MappingProxyType({wire: code for code, wire in VISIBILITY_WIRE.items()})
COMPANY_SIZE_BY_WIRE = MappingProxyType({wire: code for code, wire in COMPANY_SIZE_WIRE.items()})


class ContactSource(IntEnum):
    MANUAL = 1
    CSV = 2
    WEB_FORM = 3
    EMAIL = 4


CONTACT_SOURCE_WIRE = MappingProxyType(
    {
        ContactSource.MANUAL: "manual",
        ContactSource.CSV: "csv",
        ContactSource.WEB_FORM: "web_form",
        ContactSource.EMAIL: "email",
    }
)
CONTACT_STATUS_BY_WIRE = MappingProxyType({"active": False, "opted_out": True})
