"""Builds the pytest database nudge_test from the SQL files. Used only by conftest.py.

The real schema is never created by Django (no migrate). Each test session drops nudge_test,
creates it
again, runs the no-pgvector schema and the seed, and checks the result. Refuses anything but a local
database whose name ends with _test, so a wrong URL can never drop the development database.
"""

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit

import psycopg
from psycopg import sql

from common.messages import Messages

LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1"})
TEST_DB_SUFFIX = "_test"
MAINTENANCE_DB = "postgres"
DEFAULT_PORT = 5432
CONNECT_TIMEOUT_SECONDS = 5

EXPECTED_TABLES = 50
EXPECTED_LABELS = 13
REQUIRED_FUNCTION = "nudge_uuid_v7"


class TestDatabaseRefused(Exception):
    __test__ = False  # not a pytest test class

    def __init__(self, message: Messages, *values: object) -> None:
        super().__init__(message.render(*values))
        self.message = message


@dataclass(frozen=True, slots=True)
class DbTarget:
    host: str
    port: int
    name: str
    user: str
    password: str

    def connect(self, dbname: str) -> psycopg.Connection:
        return psycopg.connect(
            host=self.host,
            port=self.port,
            dbname=dbname,
            user=self.user,
            password=self.password,
            connect_timeout=CONNECT_TIMEOUT_SECONDS,
            autocommit=True,
        )


def parse_target(url: str) -> DbTarget:
    parts = urlsplit(url)
    return DbTarget(
        host=parts.hostname or "",
        port=parts.port or DEFAULT_PORT,
        name=unquote(parts.path.lstrip("/")),
        user=unquote(parts.username or ""),
        password=unquote(parts.password or ""),
    )


def assert_safe_test_target(target: DbTarget, dev_name: str) -> None:
    if target.host not in LOCAL_HOSTS:
        raise TestDatabaseRefused(Messages.TESTDB_REMOTE_HOST, target.host)
    if not target.name.endswith(TEST_DB_SUFFIX) or target.name == dev_name:
        raise TestDatabaseRefused(Messages.TESTDB_UNSAFE_NAME, target.name, dev_name)


def build_test_database(target: DbTarget, dev_name: str, schema_sql: Path, seed_sql: Path) -> None:
    """Drop and recreate target.name, then load the schema and the seed. Every check runs before
    connecting."""
    assert_safe_test_target(target, dev_name)
    for path in (schema_sql, seed_sql):
        if not Path(path).is_file():
            raise TestDatabaseRefused(Messages.TESTDB_SQL_MISSING, path)

    database = sql.Identifier(target.name)
    with target.connect(MAINTENANCE_DB) as admin:
        admin.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(database))
        admin.execute(
            sql.SQL("CREATE DATABASE {} ENCODING 'UTF8' TEMPLATE template0").format(database)
        )

    with target.connect(target.name) as conn:
        # Each file is one script with its own BEGIN/COMMIT, so it loads all or nothing.
        conn.execute(Path(schema_sql).read_text(encoding="utf-8"))
        conn.execute(Path(seed_sql).read_text(encoding="utf-8"))
        verify_test_database(conn)


def verify_test_database(conn: psycopg.Connection) -> None:
    def scalar(query: str) -> object:
        return conn.execute(query).fetchone()[0]

    tables = scalar(
        "select count(*) from information_schema.tables "
        "where table_schema = 'public' and table_type = 'BASE TABLE'"
    )
    if tables != EXPECTED_TABLES:
        raise TestDatabaseRefused(Messages.TESTDB_TABLE_COUNT, tables, EXPECTED_TABLES)
    functions = conn.execute(
        "select count(*) from pg_proc where proname = %s", [REQUIRED_FUNCTION]
    ).fetchone()[0]
    if functions != 1:
        raise TestDatabaseRefused(Messages.TESTDB_FUNCTION_MISSING, REQUIRED_FUNCTION)
    labels = scalar("select count(*) from labels")
    if labels != EXPECTED_LABELS:
        raise TestDatabaseRefused(Messages.TESTDB_LABEL_COUNT, labels, EXPECTED_LABELS)
