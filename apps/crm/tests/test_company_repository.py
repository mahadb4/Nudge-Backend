"""PostgresCompanyRepository directly: the guards that the API tests cannot reach one by one (the
service checks them too), and tenant isolation for every method."""

from datetime import timedelta

import pytest
from django.db import transaction as db_transaction

from apps.crm.domain.errors import DuplicateCompanyDomain
from apps.crm.repositories.company_repository import PostgresCompanyRepository
from common.constants import Role
from common.pagination import parse_list_query
from common.tenancy import TenantContext
from config import container

pytestmark = pytest.mark.django_db


@pytest.fixture
def repo() -> PostgresCompanyRepository:
    return PostgresCompanyRepository()


def ctx(tenancy, name: str):
    organization_id = tenancy.organization(name)
    person = tenancy.member(Role.OWNER, organization_id)
    return TenantContext(person.user_id, organization_id, Role.OWNER)


def values(context, name="Acme", domain=None) -> dict:
    return {
        "name": name,
        "domain": domain,
        "owner_id": context.user_id,
        "visibility": 3,
        "team_id": None,
    }


def add(repo, context, name="Acme", **kwargs):
    return repo.create(context, container.ids().new_id(), values(context, name, **kwargs))


def test_update_only_applies_when_updated_at_is_still_the_one_read(tenancy, repo):
    context = ctx(tenancy, "A")
    company = add(repo, context)
    now = company.updated_at + timedelta(seconds=5)
    assert not repo.update(
        context, company.id, company.updated_at - timedelta(seconds=1), {"name": "Stale"}, now
    )
    assert repo.get(context, company.id).company.name == "Acme"
    assert repo.update(context, company.id, company.updated_at, {"name": "Fresh"}, now)
    assert repo.get(context, company.id).company.name == "Fresh"
    assert not repo.update(context, company.id, company.updated_at, {"name": "Again"}, now)


def test_every_method_is_blind_to_another_organization(tenancy, repo):
    a, b = ctx(tenancy, "A"), ctx(tenancy, "B")
    company = add(repo, a, "Shared Name", domain="shared.com")
    query = parse_list_query({}, orderings=("name",), default_ordering="name")
    assert repo.list_page(b, query).count == 0
    assert repo.get(b, company.id) is None and repo.get(b, company.id, visible_only=False) is None
    assert not repo.name_taken(b, "Shared Name", None)
    assert not repo.domain_taken(b, "shared.com", None)
    assert not repo.update(b, company.id, company.updated_at, {"name": "Taken"}, company.updated_at)
    assert not repo.soft_delete(b, company.id, company.updated_at)
    assert not repo.is_active_member(b, a.user_id)
    assert repo.get(a, company.id).company.name == "Shared Name"
    assert repo.soft_delete(a, company.id, company.updated_at)


def test_a_duplicate_live_domain_raises_but_a_deleted_one_does_not(tenancy, repo):
    context = ctx(tenancy, "A")
    first = add(repo, context, "One", domain="dup.com")
    with pytest.raises(DuplicateCompanyDomain), db_transaction.atomic():
        add(repo, context, "Two", domain="dup.com")
    repo.soft_delete(context, first.id, first.updated_at)
    assert add(repo, context, "Three", domain="dup.com")
