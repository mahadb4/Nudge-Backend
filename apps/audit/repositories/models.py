"""Unmanaged ORM model of audit_logs. Private to the repositories. The table is append-only (a
trigger enforces it)."""

from django.db import models
from django.db.models.functions import Now


class AuditLogModel(models.Model):
    id = models.UUIDField(primary_key=True)
    organization_id = models.UUIDField(null=True)
    actor_id = models.UUIDField(null=True)
    actor_type = models.SmallIntegerField()
    action = models.CharField(max_length=60)
    object_type = models.CharField(max_length=40, null=True)
    object_id = models.UUIDField(null=True)
    details = models.JSONField(default=dict)
    ip_address = models.GenericIPAddressField(null=True)
    created_at = models.DateTimeField(db_default=Now())

    class Meta:
        managed = False
        db_table = "audit_logs"
