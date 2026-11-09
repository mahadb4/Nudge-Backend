"""Format rules for the account inputs. Never touches the database (CODING_STYLE 2).

Every field is checked and every failing field is reported together, as one ValidationFailed.
"""

from typing import cast

from apps.accounts.domain.entities import (
    LoginData,
    PasswordChangeData,
    RegisterData,
    VerifyData,
)
from common.constants import AccountType
from common.errors import ValidationFailed
from common.messages import Messages
from common.validators import (
    FieldErrors,
    is_reset_token_format,
    validate_account_type,
    validate_bool,
    validate_code,
    validate_company_for_type,
    validate_email,
    validate_login_password,
    validate_password,
    validate_person_name,
    validate_timezone,
)


class UserValidator:
    def validate_register(
        self,
        *,
        name: object,
        company: object,
        email: object,
        password: object,
        account_type: object,
        timezone: object,
    ) -> RegisterData:
        errors = FieldErrors()
        kind = errors.check("type", validate_account_type, account_type)
        full_name = errors.check("name", validate_person_name, name)
        # The company rule depends on the account type, so it is only checked when the type itself
        # is valid.
        company_name = (
            errors.check("company", validate_company_for_type, company, kind)
            if kind is not None
            else None
        )
        clean_email = errors.check("email", validate_email, email)
        clean_timezone = errors.check("timezone", validate_timezone, timezone)
        clean_password = errors.check(
            "password", validate_password, password, email=clean_email, full_name=full_name
        )
        errors.raise_if_any()
        return RegisterData(
            full_name=cast(str, full_name),
            company=company_name,
            email=cast(str, clean_email),
            password=cast(str, clean_password),
            account_type=cast(AccountType, kind),
            timezone=cast(str, clean_timezone),
        )

    def validate_verify(self, *, email: object, code: object) -> VerifyData:
        errors = FieldErrors()
        clean_email = errors.check("email", validate_email, email)
        clean_code = errors.check("code", validate_code, code)
        errors.raise_if_any()
        return VerifyData(email=cast(str, clean_email), code=cast(str, clean_code))

    def validate_email_only(self, *, email: object) -> str:
        errors = FieldErrors()
        clean_email = errors.check("email", validate_email, email)
        errors.raise_if_any()
        return cast(str, clean_email)

    def validate_login(self, *, email: object, password: object, remember: object) -> LoginData:
        errors = FieldErrors()
        clean_email = errors.check("email", validate_email, email)
        clean_password = errors.check("password", validate_login_password, password)
        # "Keep me signed in" is optional; leaving it out means no.
        keep = False if remember is None else errors.check("remember", validate_bool, remember)
        errors.raise_if_any()
        return LoginData(
            email=cast(str, clean_email), password=cast(str, clean_password), remember=bool(keep)
        )

    def validate_password_change(
        self, *, current: object, password: object, email: str, full_name: str
    ) -> PasswordChangeData:
        errors = FieldErrors()
        clean_current = errors.check("current", validate_login_password, current)
        # The "same as current" rule needs the plain current password, so only when it is usable.
        clean_password = errors.check(
            "password",
            validate_password,
            password,
            email=email,
            full_name=full_name,
            current=clean_current,
        )
        errors.raise_if_any()
        return PasswordChangeData(
            current=cast(str, clean_current), password=cast(str, clean_password)
        )

    def validate_new_password(self, *, password: object, email: str, full_name: str) -> str:
        errors = FieldErrors()
        clean_password = errors.check(
            "password", validate_password, password, email=email, full_name=full_name
        )
        errors.raise_if_any()
        return cast(str, clean_password)

    def check_reset_token(self, token: object) -> str:
        """A wrong shape is the same 400 as a wrong or used token."""
        if not is_reset_token_format(token):
            raise ValidationFailed(Messages.AUTH_INVALID_TOKEN)
        return cast(str, token)
