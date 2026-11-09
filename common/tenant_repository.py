"""Base for repositories of tenant-owned tables. Every query starts from _rows(context), which is
already filtered by organization, so a forgotten filter cannot leak another organization's data.

Rule (checked by test_architecture): every public method takes `context: TenantContext` first.
"""

from typing import Generic, TypeVar

from django.db import models

from common.tenancy import TenantContext

M = TypeVar("M", bound=models.Model)


class TenantRepository(Generic[M]):
    model: type[M]

    def _rows(self, context: TenantContext) -> models.QuerySet[M]:
        return self.model.objects.filter(organization_id=context.organization_id)
