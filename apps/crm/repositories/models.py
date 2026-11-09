"""Unmanaged ORM models of the tables crm uses. Private to the repositories: nothing else imports
this file."""

from django.db import models
from django.db.models.functions import Now


class DealStageModel(models.Model):
    id = models.UUIDField(primary_key=True)
    organization_id = models.UUIDField()
    name = models.CharField(max_length=60)
    position = models.SmallIntegerField()
    outcome = models.SmallIntegerField(db_default=1)
    created_at = models.DateTimeField(db_default=Now())
    updated_at = models.DateTimeField(db_default=Now())

    class Meta:
        managed = False
        db_table = "deal_stages"
