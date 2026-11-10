"""Made-up data for the designed emails, used by preview_email and send_test_email --kind. Never
real user data: the name, code and links are fixed samples."""

from common.constants import EmailKind
from common.interfaces import EmailMessage
from common.messages import Messages

SAMPLE_NAME = "Ali Raza"
SAMPLE_CODE = "123456"
SAMPLE_SIGN_IN_LINK = "http://localhost:5173/sign-in"
SAMPLE_RESET_LINK = "http://localhost:5173/new-password?token=sample-token"


def sample_message(kind: EmailKind, to: str = "") -> EmailMessage:
    """The same message the real flow builds for this kind, filled with sample values."""
    if kind is EmailKind.VERIFY_CODE:
        return EmailMessage(
            to=to,
            subject=Messages.EMAIL_VERIFY_CODE_SUBJECT.value,
            text_body=Messages.EMAIL_VERIFY_CODE_BODY.render(SAMPLE_CODE),
            kind=kind,
            recipient_name=SAMPLE_NAME,
            code=SAMPLE_CODE,
        )
    if kind is EmailKind.REGISTER_EXISTING:
        return EmailMessage(
            to=to,
            subject=Messages.EMAIL_REGISTER_EXISTING_SUBJECT.value,
            text_body=Messages.EMAIL_REGISTER_EXISTING_BODY.render(SAMPLE_SIGN_IN_LINK),
            kind=kind,
            recipient_name=SAMPLE_NAME,
            link=SAMPLE_SIGN_IN_LINK,
        )
    return EmailMessage(
        to=to,
        subject=Messages.EMAIL_RESET_LINK_SUBJECT.value,
        text_body=Messages.EMAIL_RESET_LINK_BODY.render(SAMPLE_RESET_LINK),
        kind=kind,
        recipient_name=SAMPLE_NAME,
        link=SAMPLE_RESET_LINK,
    )
