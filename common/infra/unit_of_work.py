"""One database transaction for a use case (a registration writes five tables or none)."""

from contextlib import AbstractContextManager

from django.db import transaction


class DjangoUnitOfWork:
    def atomic(self) -> AbstractContextManager[None]:
        return transaction.atomic()
