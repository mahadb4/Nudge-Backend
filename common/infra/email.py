"""The EmailSender Protocol on top of Django's mail backend (console in development, SMTP when the
environment says so).

Three senders, chosen per path in config/container.py:
- DjangoEmailSender is strict: any delivery failure is logged (without secrets) and raised as
  ServiceUnavailable, which the API answers with 503.
- HtmlEmailSender wraps it and adds the HTML version of the designed emails.
- QuietEmailSender wraps it for paths where a failure must not change the answer (sign-up, resend,
  forgot password: the reply must not reveal whether an address exists; and notices sent after a
  committed change). The failure is logged and swallowed.

Synchronous for now. Once a worker queue exists these classes move behind it without touching any
service.
"""

import logging
import smtplib
from dataclasses import replace

from django.conf import settings
from django.core.mail import send_mail

from common.email_templates.renderer import EmailRenderer
from common.errors import ServiceUnavailable
from common.interfaces import EmailMessage, EmailSender

logger = logging.getLogger(__name__)


class DjangoEmailSender:
    def send(self, message: EmailMessage) -> None:
        try:
            send_mail(
                message.subject,
                message.text_body,
                settings.DEFAULT_FROM_EMAIL,
                [message.to],
                fail_silently=False,
                html_message=message.html_body,
            )
        except (smtplib.SMTPException, OSError) as exc:
            # Only the kind of failure and the SMTP status code. Never the exception text (a
            # server reply can echo a login), the settings, the recipient or the body.
            logger.error(
                "Email delivery failed: %s (smtp_code=%s, errno=%s) subject=%r",
                type(exc).__name__,
                getattr(exc, "smtp_code", None),
                getattr(exc, "errno", None),
                message.subject,
            )
            raise ServiceUnavailable() from None


class HtmlEmailSender:
    """Adds the designed HTML version to a message that has a kind, then hands it on. The text
    version is untouched, so the mail goes out as multipart/alternative with the same facts."""

    def __init__(self, inner: EmailSender, renderer: EmailRenderer) -> None:
        self._inner = inner
        self._renderer = renderer

    def send(self, message: EmailMessage) -> None:
        html = self._renderer.render_html(message)
        self._inner.send(replace(message, html_body=html) if html else message)


class QuietEmailSender:
    """Sends like the wrapped sender, but a failure (already logged) does not reach the caller."""

    def __init__(self, inner: EmailSender) -> None:
        self._inner = inner

    def send(self, message: EmailMessage) -> None:
        try:
            self._inner.send(message)
        except ServiceUnavailable:
            return
