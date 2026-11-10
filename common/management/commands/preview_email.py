"""python manage.py preview_email verify_code|register_existing|reset_link

Writes the rendered HTML of one designed email, filled with sample values, to a temporary file to
open in a browser. Nothing is sent. Development only (same guard as send_test_email).
"""

import tempfile
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import connection

from common.constants import EmailKind
from common.management.email_samples import sample_message
from common.management.guard import assert_dev_only
from common.messages import Messages
from config import container


class Command(BaseCommand):
    help = "Write the HTML of one designed email to a temporary file (development only)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("kind", choices=[kind.value for kind in EmailKind])

    def handle(self, *args: object, **options: object) -> None:
        assert_dev_only(
            "preview_email",
            settings_module=settings.SETTINGS_MODULE,
            debug=settings.DEBUG,
            database_name=connection.settings_dict["NAME"],
            dev_database_name=settings.DEV_DATABASE_NAME,
        )
        kind = EmailKind(str(options["kind"]))
        message = sample_message(kind)
        html = container.email_renderer().render_html(message)
        if html is None:
            raise CommandError(Messages.CLI_PREVIEW_EMAIL_FAILED.render())
        with tempfile.NamedTemporaryFile(
            "w", suffix=f"-{kind.value}.html", delete=False, encoding="utf-8"
        ) as handle:
            handle.write(html)
        self.stdout.write(Messages.CLI_PREVIEW_EMAIL_WRITTEN.render(kind.value, Path(handle.name)))
