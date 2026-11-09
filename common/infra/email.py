"""The EmailSender Protocol on top of Django's mail backend (console in development, SMTP later).

Synchronous for now. Once a worker queue exists this class moves behind it without touching any
service.
"""

import smtplib

from django.conf import settings
from django.core.mail import send_mail

from common.errors import ServiceUnavailable
from common.interfaces import EmailMessage


class DjangoEmailSender:
    def send(self, message: EmailMessage) -> None:
        try:
            send_mail(
                message.subject,
                message.text_body,
                settings.DEFAULT_FROM_EMAIL,
                [message.to],
                fail_silently=False,
            )
        except (smtplib.SMTPException, OSError) as exc:
            raise ServiceUnavailable() from exc
