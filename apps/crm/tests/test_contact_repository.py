"""PostgresContactRepository directly: guards the service also checks, and tenant isolation for
every method."""

from datetime import timedelta

import pytest
from django.db import transaction as db_transaction

from apps.crm.domain.errors import DuplicateContactEmail
from apps.crm.repositories.contact_repository import PostgresContactRepository
from common.constants import Role
from common.pagination import parse_list_query
from common.tenancy import TenantContext
from config import container

pytestmark = pytest.mark.django_db


@pytest.fixture
def repo() -> PostgresContactRepository:
    return PostgresContactRepository()


def ctx(tenancy, name: str) -> TenantContext:
    organization_id = tenancy.organization(name)
    person = tenancy.member(Role.OWNER, organization_id)
    return TenantContext(person.user_id, organization_id, Role.OWNER)


def add(repo, context, first="Ada", email="ada@example.com"):
    return repo.create(
        context,
        container.ids().new_id(),
        {
            "first_name": first,
            "email": email,
            "owner_id": context.user_id,
            "visibility": 3,
            "team_id": None,
            "company_id": None,
        },
    )


def test_update_only_applies_when_updated_at_is_still_the_one_read(tenancy, repo):
    context = ctx(tenancy, "A")
    contact = add(repo, context)
    now = contact.updated_at + timedelta(seconds=5)
    stale = contact.updated_at - timedelta(seconds=1)
    assert not repo.update(context, contact.id, stale, {"job_title": "Stale"}, now)
    assert repo.update(context, contact.id, contact.updated_at, {"job_title": "Fresh"}, now)
    assert repo.get(context, contact.id).contact.job_title == "Fresh"
    assert not repo.update(context, contact.id, contact.updated_at, {"job_title": "Again"}, now)


def test_every_method_is_blind_to_another_organization(tenancy, repo):
    a, b = ctx(tenancy, "A"), ctx(tenancy, "B")
    contact = add(repo, a, "Shared", "shared@example.com")
    query = parse_list_query({}, orderings=("name",), default_ordering="name")
    assert repo.list_page(b, query).count == 0
    assert repo.get(b, contact.id) is None and repo.get(b, contact.id, visible_only=False) is None
    assert repo.find_by_email(b, "shared@example.com", None) is None
    assert not repo.update(
        b, contact.id, contact.updated_at, {"job_title": "X"}, contact.updated_at
    )
    assert not repo.soft_delete(b, contact.id, contact.updated_at)
    assert not repo.is_active_member(b, a.user_id)
    assert repo.get(a, contact.id).contact.first_name == "Shared"
    assert repo.soft_delete(a, contact.id, contact.updated_at)


def test_a_company_of_another_organization_is_never_visible(tenancy, repo):
    a, b = ctx(tenancy, "A"), ctx(tenancy, "B")
    company = container.company_service().create(a, {"name": "Acme"}, None)
    assert repo.company_is_visible(a, company.company.id)
    assert not repo.company_is_visible(b, company.company.id)


def test_a_duplicate_live_email_raises_but_a_deleted_one_does_not(tenancy, repo):
    context = ctx(tenancy, "A")
    first = add(repo, context, "One", "dup@example.com")
    with pytest.raises(DuplicateContactEmail), db_transaction.atomic():
        add(repo, context, "Two", "dup@example.com")
    repo.soft_delete(context, first.id, first.updated_at)
    assert add(repo, context, "Three", "dup@example.com")
