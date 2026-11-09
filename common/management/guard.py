"""Base for commands that must never run against the nudge schema.

Each refused command subclasses Django's own command, so its arguments and --help work exactly as
usual,
and only handle() is replaced: it raises before any database work.
"""

from django.core.management import CommandError

from common.messages import Messages


class RefusedCommandMixin:
    refused_name: str

    def handle(self, *args: object, **options: object) -> None:
        raise CommandError(Messages.CLI_COMMAND_REFUSED.render(self.refused_name))
