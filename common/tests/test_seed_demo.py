"""seed_demo: the guard, and the seeder against nudge_test only. The real nudge database is never
touched: under the test settings the command itself refuses, so the seeder is called directly."""

import re

import pytest
from django.core.management import CommandError, call_command
from django.db import connection
from rest_framework.test import APIClient

from common.errors import Unauthorized
from common.management.demo_data import (
    DEMO_COMPANIES,
    DEMO_CONTACTS,
    DEMO_ORGANIZATION,
)
from common.management.demo_seeder import new_email, new_password
from common.management.guard import assert_dev_only
from config import container

pytestmark = pytest.mark.django_db

DEV = "nudge"
GOOD = dict(
    settings_module="config.settings.dev", debug=True, database_name=DEV, dev_database_name=DEV
)


def count(table: str, where: str = "true") -> int:
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT count(*) FROM {table} WHERE {where}")
        return cursor.fetchone()[0]


# ---- the guard


def test_the_guard_allows_only_dev_settings_debug_and_the_dev_database():
    assert_dev_only("seed_demo", **GOOD)


@pytest.mark.parametrize(
    "override",
    [
        {"settings_module": "config.settings.test"},
        {"settings_module": "config.settings.prod"},
        {"settings_module": ""},
        {"debug": False},
        {"database_name": "nudge_test"},
        {"database_name": "other"},
        {"database_name": ""},
    ],
)
def test_the_guard_refuses_everything_else(override):
    with pytest.raises(CommandError):
        assert_dev_only("seed_demo", **{**GOOD, **override})


def test_the_command_refuses_under_the_test_settings_and_writes_nothing():
    before = (count("organizations"), count("users"))
    with pytest.raises(CommandError) as info:
        call_command("seed_demo")
    assert "config.settings.dev" in str(info.value)
    assert (count("organizations"), count("users")) == before


# ---- the seeder (on nudge_test)


@pytest.fixture
def seeder():
    return container.demo_seeder()


def test_it_builds_one_workspace_with_the_default_stages_companies_and_contacts(seeder):
    result = seeder.run()
    assert result.created and result.organization_name == DEMO_ORGANIZATION
    assert (result.stages, result.companies, result.contacts) == (
        7,
        len(DEMO_COMPANIES),
        len(DEMO_CONTACTS),
    )
    assert (len(DEMO_COMPANIES), len(DEMO_CONTACTS)) == (8, 25)
    assert count("organizations", f"name = '{DEMO_ORGANIZATION}'") == 1
    assert count("deal_stages") >= 7


def test_the_owner_is_verified_and_can_sign_in_with_the_printed_credentials(seeder):
    result = seeder.run()
    assert re.fullmatch(r"demo-[0-9a-f]{8}@example\.com", result.owner_email)
    assert result.password and result.password not in result.owner_email
    assert count("users", f"email = '{result.owner_email}' AND email_verified_at IS NOT NULL") == 1
    assert count("memberships", "role = 1 AND status = 1") >= 1
    signed_in = container.sign_in_service().login(
        email=result.owner_email,
        password=result.password,
        remember=False,
        ip_address="203.0.113.5",
        user_agent=None,
    )
    assert signed_in.me.current.organization.name == DEMO_ORGANIZATION
    with pytest.raises(Unauthorized):
        container.sign_in_service().login(
            email=result.owner_email,
            password=result.password + "x",
            remember=False,
            ip_address="203.0.113.6",
            user_agent=None,
        )


def test_the_password_is_stored_only_as_a_hash(seeder):
    result = seeder.run()
    with connection.cursor() as cursor:
        cursor.execute("SELECT password FROM users WHERE email = %s", [result.owner_email])
        (stored,) = cursor.fetchone()
    assert result.password not in stored and stored.startswith("argon2$")


def test_the_data_shows_up_through_the_api_for_the_owner(seeder):
    result = seeder.run()
    signed = container.sign_in_service().login(
        email=result.owner_email,
        password=result.password,
        remember=False,
        ip_address="203.0.113.7",
        user_agent=None,
    )
    headers = {"HTTP_AUTHORIZATION": f"Bearer {signed.tokens.access_token}"}
    client = APIClient()
    contacts = client.get("/api/v1/contacts/?page_size=100", **headers).json()
    companies = client.get("/api/v1/companies/", **headers).json()
    stages = client.get("/api/v1/deal-stages/", **headers).json()
    assert (contacts["count"], companies["count"], len(stages)) == (25, 8, 7)
    assert all(c["people_count"] >= 2 for c in companies["results"])
    assert any(c["company"] is None for c in contacts["results"])
    assert all(c["owner"]["name"] == "Demo Owner" for c in contacts["results"])


def test_every_contact_and_company_has_valid_realistic_data(seeder):
    seeder.run()
    assert count("contacts", "phone IS NOT NULL") >= 15
    assert count("contacts", "email IS NULL") == 0
    assert count("companies", "domain IS NULL OR size_range IS NULL OR industry IS NULL") == 0


def test_running_twice_duplicates_nothing_and_does_not_show_the_password_again(seeder):
    first = seeder.run()
    counts = {
        t: count(t)
        for t in ("organizations", "users", "memberships", "companies", "contacts", "deal_stages")
    }
    second = seeder.run()
    assert not second.created and second.password is None
    assert second.owner_email == first.owner_email
    assert (second.stages, second.companies, second.contacts) == (7, 8, 25)
    assert {t: count(t) for t in counts} == counts


def test_a_second_run_tops_up_what_was_deleted_and_keeps_the_rest(seeder):
    seeder.run()
    with connection.cursor() as cursor:
        cursor.execute("UPDATE contacts SET deleted_at = now() WHERE first_name = 'Ayesha'")
    again = seeder.run()
    assert again.contacts == 25 and count("contacts", "deleted_at IS NULL") == 25
    assert count("contacts", "first_name = 'Ayesha'") == 2  # the soft-deleted row and the new one


def test_reset_password_gives_a_new_one_and_the_old_one_stops_working(seeder):
    first = seeder.run()
    reset = seeder.run(reset_password=True)
    assert reset.password and reset.password != first.password and not reset.created
    with pytest.raises(Unauthorized):
        container.sign_in_service().login(
            email=first.owner_email,
            password=first.password,
            remember=False,
            ip_address="203.0.113.8",
            user_agent=None,
        )
    assert container.sign_in_service().login(
        email=first.owner_email,
        password=reset.password,
        remember=False,
        ip_address="203.0.113.9",
        user_agent=None,
    )


def test_other_organizations_are_left_alone(tenancy, seeder):
    other = tenancy.organization("Somebody Else")
    before = count("deal_stages", f"organization_id = '{other}'")
    seeder.run()
    assert count("organizations", f"id = '{other}'") == 1
    assert count("deal_stages", f"organization_id = '{other}'") == before
    assert count("companies", f"organization_id = '{other}'") == 0


def test_the_writes_are_audited_like_api_writes(seeder):
    seeder.run()
    assert count("audit_logs", "action = 'company.create'") == 8
    assert count("audit_logs", "action = 'contact.create'") == 25


def test_generated_credentials_are_random_and_meet_the_password_rules():
    passwords = {new_password() for _ in range(20)}
    assert len(passwords) == 20
    for password in passwords:
        assert re.search(r"[a-z]", password) and re.search(r"[A-Z]", password)
        assert re.search(r"[0-9]", password) and len(password) >= 12
    assert len({new_email() for _ in range(20)}) == 20


def test_no_credentials_are_written_in_the_source():
    from pathlib import Path

    source = Path("common/management").glob("*.py")
    text = "\n".join(p.read_text(encoding="utf-8") for p in source)
    assert 'password="' not in text and "demo@" not in text
