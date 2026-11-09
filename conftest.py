"""Project-wide pytest fixtures.

django_db_setup replaces pytest-django's default, which would run migrate. Instead nudge_test is
rebuilt
from the SQL files once per session (common/testdb.py). Each test still runs inside a transaction
that is
rolled back (pytest-django's db fixture).
"""

import pytest
from django.conf import settings
from django.db import connection

from common.testdb import build_test_database, parse_target


@pytest.fixture(scope="session")
def django_db_setup(django_db_blocker):
    with django_db_blocker.unblock():
        connection.close()
        build_test_database(
            parse_target(settings.TEST_DATABASE_URL),
            dev_name=settings.DEV_DATABASE_NAME,
            schema_sql=settings.NUDGE_SCHEMA_SQL,
            seed_sql=settings.NUDGE_SEED_SQL,
        )


@pytest.fixture(autouse=True)
def _immediate_constraints(request):
    """Composite tenant FKs are DEFERRABLE INITIALLY DEFERRED and the test transaction never
    commits,
    so without this a cross-organization link would never fail inside a test."""
    if "db" not in request.fixturenames and request.node.get_closest_marker("django_db") is None:
        return
    request.getfixturevalue("db")
    with connection.cursor() as cursor:
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
