"""Guards for commands that must not run against the wrong database.

RefusedCommandMixin: commands that never run (migrate and friends). Each subclasses Django's own
command, so its arguments and --help work exactly as usual, and only handle() is replaced: it
raises before any database work.

assert_demo_allowed: seed_demo only runs with the development settings, DEBUG on, and connected
to the development database.
"""

from django.core.management import CommandError

from common.messages import Messages

DEV_SETTINGS_MODULE = "config.settings.dev"


class RefusedCommandMixin:
    refused_name: str

    def handle(self, *args: object, **options: object) -> None:
        raise CommandError(Messages.CLI_COMMAND_REFUSED.render(self.refused_name))


def assert_dev_only(
    command: str, *, settings_module: str, debug: bool, database_name: str, dev_database_name: str
) -> None:
    """Raises CommandError unless every condition holds."""
    if settings_module != DEV_SETTINGS_MODULE:
        raise CommandError(Messages.CLI_DEV_ONLY_SETTINGS.render(command, settings_module))
    if not debug:
        raise CommandError(Messages.CLI_DEV_ONLY_DEBUG.render(command))
    if database_name != dev_database_name:
        raise CommandError(
            Messages.CLI_DEV_ONLY_DATABASE.render(command, dev_database_name, database_name)
        )
