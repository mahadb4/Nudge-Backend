"""The test database built from the SQL file matches the schema, and composite FKs fail inside the
test."""

import uuid

import pytest
from django.db import IntegrityError, connection

pytestmark = pytest.mark.django_db


def scalar(sql):
    with connection.cursor() as cur:
        cur.execute(sql)
        return cur.fetchone()[0]


def test_connected_to_the_test_database_not_nudge():
    assert scalar("select current_database()") == "nudge_test"


def test_has_exactly_50_tables():
    assert (
        scalar(
            "select count(*) from information_schema.tables "
            "where table_schema = 'public' and table_type = 'BASE TABLE'"
        )
        == 50
    )


def test_no_django_tables_so_migrate_never_ran():
    assert (
        scalar(
            "select count(*) from information_schema.tables where table_schema = 'public' "
            "and (table_name like 'django%%' or table_name like 'auth%%')"
        )
        == 0
    )


def test_uuid_v7_function_returns_version_7():
    assert uuid.UUID(str(scalar("select nudge_uuid_v7()"))).version == 7


def test_default_stages_function_exists():
    assert scalar("select count(*) from pg_proc where proname = 'nudge_create_default_stages'") == 1


def test_seed_labels_present():
    assert scalar("select count(*) from label_sets") == 2
    assert scalar("select count(*) from labels") == 13


def test_btree_gist_installed():
    assert scalar("select count(*) from pg_extension where extname = 'btree_gist'") == 1


def test_no_pgvector_variant():
    assert (
        scalar(
            "select udt_name from information_schema.columns "
            "where table_name = 'email_chunks' and column_name = 'embedding'"
        )
        == "_float4"
    )


def test_cross_organization_link_fails_inside_the_test():
    """SET CONSTRAINTS ALL IMMEDIATE (conftest) makes the deferred composite FK fail at the INSERT,
    not at commit."""
    with connection.cursor() as cur:
        cur.execute(
            "insert into users (email, password, full_name, timezone) "
            "values ('a@example.com', 'x', 'A', 'UTC') returning id"
        )
        user_id = cur.fetchone()[0]
        cur.execute(
            "insert into organizations (name, account_type, timezone) "
            "values ('Org A', 2, 'UTC') returning id"
        )
        org_a = cur.fetchone()[0]
        cur.execute(
            "insert into organizations (name, account_type, timezone) "
            "values ('Org B', 2, 'UTC') returning id"
        )
        org_b = cur.fetchone()[0]
        cur.execute(
            "insert into memberships (organization_id, user_id, role) "
            "values (%s, %s, 1) returning id",
            [org_a, user_id],
        )
        membership_a = cur.fetchone()[0]
        cur.execute(
            "insert into teams (organization_id, name) values (%s, 'Sales') returning id", [org_b]
        )
        team_b = cur.fetchone()[0]
        with pytest.raises(IntegrityError):
            cur.execute(
                "insert into team_members (organization_id, team_id, membership_id) "
                "values (%s, %s, %s)",
                [org_a, team_b, membership_a],
            )
