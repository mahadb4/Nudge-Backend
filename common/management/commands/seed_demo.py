"""python manage.py seed_demo [--reset-password]

Builds a filled demo workspace for the development database. Refuses anywhere else.
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandParser
from django.db import connection

from common.management.guard import assert_dev_only
from common.messages import Messages
from config import container


class Command(BaseCommand):
    help = "Create (or top up) the demo workspace on the development database."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--reset-password",
            action="store_true",
            help="Give the demo Owner a new random password and show it.",
        )

    def handle(self, *args: object, **options: object) -> None:
        assert_dev_only(
            "seed_demo",
            settings_module=settings.SETTINGS_MODULE,
            debug=settings.DEBUG,
            database_name=connection.settings_dict["NAME"],
            dev_database_name=settings.DEV_DATABASE_NAME,
        )
        result = container.demo_seeder().run(reset_password=bool(options["reset_password"]))
        self.stdout.write(
            Messages.CLI_SEED_SUMMARY.render(
                result.organization_name, result.stages, result.companies, result.contacts
            )
        )
        if result.created:
            self.stdout.write(Messages.CLI_SEED_CREATED.render(result.owner_email, result.password))
        elif result.password:
            self.stdout.write(
                Messages.CLI_SEED_NEW_PASSWORD.render(result.owner_email, result.password)
            )
        else:
            self.stdout.write(Messages.CLI_SEED_EXISTS.render(result.owner_email))
