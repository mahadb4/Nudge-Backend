"""Errors the crm repositories raise for the services to translate."""


class DuplicateStageName(Exception):
    """Another stage of the organization already has this name (ignoring case)."""


class DuplicateCompanyDomain(Exception):
    """Another live company of the organization already uses this domain."""


class StaleCompany(Exception):
    """The company changed after the client read it. Carries the current version for the reply."""

    def __init__(self, current: object) -> None:
        super().__init__("stale company")
        self.current = current


class DuplicateContactEmail(Exception):
    """Another live contact of the organization already has this email."""


class ContactEmailTaken(Exception):
    """Service level: the email is in use. existing is the other contact if the caller may see
    it."""

    def __init__(self, existing: object | None) -> None:
        super().__init__("contact email taken")
        self.existing = existing


class StaleContact(Exception):
    """The contact changed after the client read it. Carries the current version for the reply."""

    def __init__(self, current: object) -> None:
        super().__init__("stale contact")
        self.current = current
