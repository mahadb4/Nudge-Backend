"""Errors a repository reports to its service. The service decides what the client is told."""


class DuplicateEmail(Exception):
    """An account with this email already exists (also when two sign-ups race)."""
