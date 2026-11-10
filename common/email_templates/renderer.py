"""Renders the designed emails. The templates in this folder only insert values; every sentence is
a line in common/messages.py. Django's template engine runs here on its own (not the project's
TEMPLATES setting) with autoescape on, so a name like <script> or a quote cannot break the markup.

Nothing in this module logs: the code and the link only ever travel inside the message.
"""

from dataclasses import dataclass
from pathlib import Path

from django.template import Context, Engine

from common.constants import EmailKind
from common.infra.clock import SystemClock
from common.interfaces import Clock, EmailMessage
from common.messages import Messages


@dataclass(frozen=True, slots=True)
class _Texts:
    template: str
    heading: Messages
    intro: Messages
    not_you: Messages
    valid: Messages | None = None
    button: Messages | None = None
    link_label: Messages | None = None


_KINDS = {
    EmailKind.VERIFY_CODE: _Texts(
        "verify_code.html",
        Messages.EMAIL_VERIFY_HEADING,
        Messages.EMAIL_VERIFY_INTRO,
        Messages.EMAIL_VERIFY_NOT_YOU,
        valid=Messages.EMAIL_VERIFY_VALID,
    ),
    EmailKind.REGISTER_EXISTING: _Texts(
        "link_action.html",
        Messages.EMAIL_EXISTING_HEADING,
        Messages.EMAIL_EXISTING_INTRO,
        Messages.EMAIL_EXISTING_NOT_YOU,
        button=Messages.EMAIL_EXISTING_BUTTON,
        link_label=Messages.EMAIL_EXISTING_LINK_LABEL,
    ),
    EmailKind.RESET_LINK: _Texts(
        "link_action.html",
        Messages.EMAIL_RESET_HEADING,
        Messages.EMAIL_RESET_INTRO,
        Messages.EMAIL_RESET_NOT_YOU,
        valid=Messages.EMAIL_RESET_VALID,
        button=Messages.EMAIL_RESET_BUTTON,
        link_label=Messages.EMAIL_RESET_LINK_LABEL,
    ),
}


def _text(message: Messages | None) -> str:
    return message.value if message else ""


class EmailRenderer:
    def __init__(self, clock: Clock | None = None) -> None:
        self._clock = clock or SystemClock()
        self._engine = Engine(
            dirs=[str(Path(__file__).resolve().parent)], autoescape=True, debug=False
        )

    def render_html(self, message: EmailMessage) -> str | None:
        """The HTML version of a message that has a kind, else None."""
        if message.kind is None:
            return None
        texts = _KINDS[message.kind]
        brand = Messages.EMAIL_BRAND_NAME.value
        context = {
            "brand_name": brand,
            "heading": texts.heading.value,
            "greeting": (
                Messages.EMAIL_GREETING.render(message.recipient_name)
                if message.recipient_name
                else ""
            ),
            "intro": texts.intro.value,
            "valid": _text(texts.valid),
            "not_you": texts.not_you.value,
            "button": _text(texts.button),
            "link_label": _text(texts.link_label),
            "code_label": Messages.EMAIL_CODE_LABEL.value,
            "code": message.code or "",
            "link": message.link or "",
            "footer_automated": Messages.EMAIL_FOOTER_AUTOMATED.value,
            "footer_brand": Messages.EMAIL_FOOTER_BRAND.render(brand, self._clock.now().year),
        }
        return self._engine.get_template(texts.template).render(Context(context))
