"""The test database builder refuses anything that is not a local *_test database. No database
needed."""

from pathlib import Path

import pytest

from common.messages import Messages
from common.testdb import (
    DbTarget,
    TestDatabaseRefused,
    assert_safe_test_target,
    build_test_database,
    parse_target,
)


def target(host="localhost", name="nudge_test", port=5432):
    return DbTarget(host=host, port=port, name=name, user="postgres", password="secret")


def refused_code(fn, *args):
    with pytest.raises(TestDatabaseRefused) as info:
        fn(*args)
    return info.value.message.name


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1"])
def test_local_test_database_is_accepted(host):
    assert_safe_test_target(target(host=host), dev_name="nudge")


@pytest.mark.parametrize("host", ["db.example.com", "10.0.0.5", "192.168.1.20", "::1", ""])
def test_any_other_host_is_refused(host):
    assert (
        refused_code(assert_safe_test_target, target(host=host), "nudge")
        == Messages.TESTDB_REMOTE_HOST.name
    )


@pytest.mark.parametrize("name", ["nudge", "nudge_tests", "test_nudge", "nudge-test", "production"])
def test_name_must_end_with_test(name):
    assert (
        refused_code(assert_safe_test_target, target(name=name), "nudge")
        == Messages.TESTDB_UNSAFE_NAME.name
    )


def test_test_name_must_differ_from_the_dev_database():
    assert (
        refused_code(assert_safe_test_target, target(name="nudge_test"), "nudge_test")
        == Messages.TESTDB_UNSAFE_NAME.name
    )


def test_parse_target_reads_every_part_and_decodes_the_password():
    t = parse_target("postgres://postgres:p%40ss%3Aword@127.0.0.1:5433/nudge_test")
    assert (t.host, t.port, t.name, t.user, t.password) == (
        "127.0.0.1",
        5433,
        "nudge_test",
        "postgres",
        "p@ss:word",
    )


def test_parse_target_defaults_the_port():
    assert parse_target("postgres://postgres@localhost/nudge_test").port == 5432


def test_missing_sql_file_is_refused_before_any_connection(tmp_path: Path):
    # Port 1 has no server: if the builder tried to connect, psycopg would raise OperationalError
    # instead.
    seed = tmp_path / "seed.sql"
    seed.write_text("select 1;", encoding="utf-8")
    code = refused_code(
        build_test_database, target(port=1), "nudge", tmp_path / "missing.sql", seed
    )
    assert code == Messages.TESTDB_SQL_MISSING.name


def test_remote_host_is_refused_before_any_connection(tmp_path: Path):
    sql = tmp_path / "s.sql"
    sql.write_text("select 1;", encoding="utf-8")
    code = refused_code(
        build_test_database, target(host="db.example.com", port=1), "nudge", sql, sql
    )
    assert code == Messages.TESTDB_REMOTE_HOST.name
