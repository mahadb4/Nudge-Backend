"""Unmanaged ORM models of the tables accounts uses. Private to the repositories: nothing else
imports this file.

Columns not listed here are never read or written by accounts; PostgreSQL fills their defaults.
Foreign keys are plain UUID columns on purpose: the database checks them, and no query can fan out
by accident.
"""

from django.db import models
from django.db.models.functions import Now


class UserModel(models.Model):
    id = models.UUIDField(primary_key=True)
    email = models.CharField(max_length=254)
    password = models.CharField(max_length=128)
    full_name = models.CharField(max_length=150)
    phone = models.CharField(max_length=20, null=True)
    timezone = models.CharField(max_length=64)
    quiet_hours_start = models.TimeField(null=True)
    quiet_hours_end = models.TimeField(null=True)
    is_active = models.BooleanField(db_default=True)
    email_verified_at = models.DateTimeField(null=True)
    last_login = models.DateTimeField(null=True)
    created_at = models.DateTimeField(db_default=Now())
    updated_at = models.DateTimeField(db_default=Now())

    class Meta:
        managed = False
        db_table = "users"


class OrganizationModel(models.Model):
    id = models.UUIDField(primary_key=True)
    name = models.CharField(max_length=150)
    account_type = models.SmallIntegerField()
    timezone = models.CharField(max_length=64)
    automation_paused_at = models.DateTimeField(null=True)
    deactivated_at = models.DateTimeField(null=True)
    created_at = models.DateTimeField(db_default=Now())
    updated_at = models.DateTimeField(db_default=Now())

    class Meta:
        managed = False
        db_table = "organizations"


class MembershipModel(models.Model):
    id = models.UUIDField(primary_key=True)
    organization_id = models.UUIDField()
    user_id = models.UUIDField()
    role = models.SmallIntegerField()
    status = models.SmallIntegerField(db_default=1)
    created_at = models.DateTimeField(db_default=Now())
    updated_at = models.DateTimeField(db_default=Now())

    class Meta:
        managed = False
        db_table = "memberships"


class SessionModel(models.Model):
    id = models.UUIDField(primary_key=True)
    user_id = models.UUIDField()
    refresh_token_hash = models.CharField(max_length=64)
    device_name = models.CharField(max_length=100, null=True)
    ip_address = models.GenericIPAddressField(null=True)
    expires_at = models.DateTimeField()
    last_used_at = models.DateTimeField(null=True)
    revoked_at = models.DateTimeField(null=True)
    created_at = models.DateTimeField(db_default=Now())

    class Meta:
        managed = False
        db_table = "user_sessions"
