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


class DealModel(models.Model):
    """Only the columns crm needs to count and sum deals per stage and per company."""

    id = models.UUIDField(primary_key=True)
    organization_id = models.UUIDField()
    stage_id = models.UUIDField()
    company_id = models.UUIDField(null=True)
    amount = models.DecimalField(max_digits=18, decimal_places=2, null=True)
    currency = models.CharField(max_length=3)
    deleted_at = models.DateTimeField(null=True)

    class Meta:
        managed = False
        db_table = "deals"


class CompanyModel(models.Model):
    id = models.UUIDField(primary_key=True)
    organization_id = models.UUIDField()
    owner_id = models.UUIDField()
    team_id = models.UUIDField(null=True)
    visibility = models.SmallIntegerField(db_default=3)
    name = models.CharField(max_length=150)
    domain = models.CharField(max_length=253, null=True)
    industry = models.CharField(max_length=80, null=True)
    size_range = models.SmallIntegerField(null=True)
    created_at = models.DateTimeField(db_default=Now())
    updated_at = models.DateTimeField(db_default=Now())
    deleted_at = models.DateTimeField(null=True)

    class Meta:
        managed = False
        db_table = "companies"


class ContactModel(models.Model):
    id = models.UUIDField(primary_key=True)
    organization_id = models.UUIDField()
    company_id = models.UUIDField(null=True)
    owner_id = models.UUIDField()
    team_id = models.UUIDField(null=True)
    visibility = models.SmallIntegerField(db_default=3)
    first_name = models.CharField(max_length=80)
    last_name = models.CharField(max_length=80, null=True)
    email = models.CharField(max_length=254, null=True)
    phone = models.CharField(max_length=20, null=True)
    job_title = models.CharField(max_length=100, null=True)
    source = models.SmallIntegerField(db_default=1)
    opted_out_at = models.DateTimeField(null=True)
    created_at = models.DateTimeField(db_default=Now())
    updated_at = models.DateTimeField(db_default=Now())
    deleted_at = models.DateTimeField(null=True)

    class Meta:
        managed = False
        db_table = "contacts"


class MemberModel(models.Model):
    """memberships, read only: who is an active member, and which membership is the caller's."""

    id = models.UUIDField(primary_key=True)
    organization_id = models.UUIDField()
    user_id = models.UUIDField()
    status = models.SmallIntegerField()

    class Meta:
        managed = False
        db_table = "memberships"


class PersonModel(models.Model):
    """users, read only: the name shown next to an owner."""

    id = models.UUIDField(primary_key=True)
    full_name = models.CharField(max_length=150)

    class Meta:
        managed = False
        db_table = "users"


class TeamModel(models.Model):
    id = models.UUIDField(primary_key=True)
    organization_id = models.UUIDField()

    class Meta:
        managed = False
        db_table = "teams"


class TeamMemberModel(models.Model):
    id = models.UUIDField(primary_key=True)
    organization_id = models.UUIDField()
    team_id = models.UUIDField()
    membership_id = models.UUIDField()

    class Meta:
        managed = False
        db_table = "team_members"
