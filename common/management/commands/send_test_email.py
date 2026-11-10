"""python manage.py send_test_email you@example.com

Sends one message through the configured email backend, to check the EMAIL_* settings. With
--kind it sends a designed email (verify_code, register_existing, reset_link) filled with sample
data, never real user data. Development only (same guard as seed_demo). On failure it says so and
exits with an error; the reason is in the log, never the password or the settings.
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import connection

from common.constants import EmailKind
from common.errors import InvalidValue, ServiceUnavailable
from common.interfaces import EmailMessage
from common.management.email_samples import sample_message
from common.management.guard import assert_dev_only
from common.messages import Messages
from common.validators import validate_email
from config import container


class Command(BaseCommand):
    help = "Send one test email to the given address (development only)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("address", help="Where to send the test message.")
        parser.add_argument(
            "--kind",
            choices=[kind.value for kind in EmailKind],
            help="Send a designed email with sample data instead of the plain test message.",
        )

    def handle(self, *args: object, **options: object) -> None:
        assert_dev_only(
            "send_test_email",
            settings_module=settings.SETTINGS_MODULE,
            debug=settings.DEBUG,
            database_name=connection.settings_dict["NAME"],
            dev_database_name=settings.DEV_DATABASE_NAME,
        )
        try:
            address = validate_email(options["address"])
        except InvalidValue as exc:
            raise CommandError(exc.issue.render()) from None
        kind = options["kind"]
        message = (
            sample_message(EmailKind(str(kind)), address)
            if kind
            else EmailMessage(
                to=address,
                subject=Messages.CLI_TEST_EMAIL_SUBJECT.value,
                text_body=Messages.CLI_TEST_EMAIL_BODY.value,
            )
        )
        try:
            container.email_sender().send(message)
        except ServiceUnavailable:
            raise CommandError(Messages.CLI_TEST_EMAIL_FAILED.render()) from None
        self.stdout.write(Messages.CLI_TEST_EMAIL_SENT.render(address, settings.EMAIL_BACKEND))
