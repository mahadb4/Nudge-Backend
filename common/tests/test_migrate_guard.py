"""Commands that would create, change or empty tables are refused before they touch any database."""

import os
import subprocess
import sys

import pytest
from django.conf import settings
from django.core.management import CommandError, call_command, get_commands

from common.messages import Messages

REFUSED = ["migrate", "makemigrations", "flush", "createcachetable", "loaddata"]


def manage(*args):
    return subprocess.run(
        [sys.executable, "manage.py", *args],
        cwd=settings.BASE_DIR,
        capture_output=True,
        text=True,
        env={**os.environ, "DJANGO_SETTINGS_MODULE": "config.settings.test"},
        timeout=60,
    )


@pytest.mark.parametrize("name", REFUSED)
def test_command_comes_from_the_common_guard(name):
    assert get_commands()[name] == "common"


@pytest.mark.parametrize(
    ("name", "args", "options"),
    [
        ("migrate", [], {}),
        ("migrate", ["accounts"], {}),
        ("migrate", [], {"run_syncdb": True}),
        ("makemigrations", [], {}),
        ("flush", [], {"interactive": False}),
        ("createcachetable", [], {}),
        ("loaddata", ["anything.json"], {}),
    ],
)
def test_command_is_refused(name, args, options):
    with pytest.raises(CommandError) as info:
        call_command(name, *args, **options)
    assert str(info.value) == Messages.CLI_COMMAND_REFUSED.render(name)


def test_manage_py_migrate_exits_with_code_1():
    result = manage("migrate")
    assert result.returncode == 1
    assert Messages.CLI_COMMAND_REFUSED.render("migrate") in result.stderr


def test_help_still_works():
    assert manage("migrate", "--help").returncode == 0
