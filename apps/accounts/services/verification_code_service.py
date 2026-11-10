"""Issue a verification code and email it. Used by sign-up and by resend."""

from apps.accounts.repositories.interfaces import VerificationCodeRepository
from common.constants import EmailKind
from common.interfaces import EmailMessage, EmailSender
from common.messages import Messages


class VerificationCodeService:
    def __init__(self, codes: VerificationCodeRepository, email: EmailSender) -> None:
        self._codes = codes
        self._email = email

    def is_live(self, email_hash: str) -> bool:
        """Is an earlier code for this email still valid (not expired, not used)?"""
        return self._codes.is_live(email_hash)

    def send_code(self, email: str, email_hash: str, name: str | None = None) -> None:
        code = self._codes.issue(email_hash)
        self._email.send(
            EmailMessage(
                to=email,
                subject=Messages.EMAIL_VERIFY_CODE_SUBJECT.value,
                text_body=Messages.EMAIL_VERIFY_CODE_BODY.render(code),
                kind=EmailKind.VERIFY_CODE,
                recipient_name=name,
                code=code,
            )
        )
