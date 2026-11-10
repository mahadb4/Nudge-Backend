"""Every sentence the API, the command line and the emails can show. One line per message.

The VALUE is the English text, with {} where a value goes. The NAME is the code sent to the
frontend:
Messages.AUTH_BAD_CREDENTIALS is sent as {"code": "AUTH_BAD_CREDENTIALS", "detail": "That email and
...."}.
The frontend decides behaviour from the name only, so changing a sentence never breaks it.
Renaming a member changes the code on the wire and needs a frontend change.

Add a new message here first, then use it. Texts must be unique (a repeated text would silently
become an
alias of the first member, so @unique stops that at import time).
"""

from enum import StrEnum, unique


@unique
class Messages(StrEnum):
    # -- Common ---- errors any endpoint can return
    COMMON_VALIDATION_FAILED = "Check the highlighted fields and try again."
    COMMON_MALFORMED_JSON = "The request body is not valid JSON."
    COMMON_INVALID_CONTENT_TYPE = "Send the request as application/json."
    COMMON_BODY_TOO_LARGE = "The request is too large."
    COMMON_FORBIDDEN = "You do not have access to that."
    COMMON_NOT_FOUND = "That could not be found."
    COMMON_METHOD_NOT_ALLOWED = "That action is not allowed here."
    COMMON_RATE_LIMITED = "Too many attempts, try again later."
    COMMON_SERVER_ERROR = "Something went wrong on our side. Try again in a moment."
    COMMON_VERSION_CONFLICT = "Someone else changed this. Reload and try again."
    COMMON_SERVICE_UNAVAILABLE = "Nudge is not available right now. Try again in a moment."

    # -- Auth ----
    AUTH_CODE_SENT = (
        "If this email can be used, a 6-digit code is on its way. It expires in 10 minutes."
    )
    AUTH_RESET_LINK_SENT = (
        "If an account exists for this email, a link is on its way. "
        "It works once and expires in an hour."
    )
    AUTH_BAD_CREDENTIALS = "That email and password do not match."
    AUTH_EMAIL_UNVERIFIED = "Verify your email before you sign in."
    AUTH_INVALID_CODE = "That code is not valid or has expired."
    AUTH_CODE_ATTEMPTS_EXCEEDED = "Too many wrong codes. Send a new code to try again."
    AUTH_INVALID_TOKEN = "This link is not valid or has expired. Ask for a new one."
    AUTH_WRONG_CURRENT_PASSWORD = "Your current password is not right."
    AUTH_ACCESS_TOKEN_INVALID = "Your session has ended. Sign in again."
    AUTH_SESSION_INVALID = "Your session has expired. Sign in again."
    AUTH_CSRF_FAILED = "Reload the page and try again."

    # -- Tenancy ----
    TENANCY_ORGANIZATION_REQUIRED = "Choose a workspace first."

    # -- Validation ---- field-level, always inside "fields"
    VALIDATION_REQUIRED = "This field is required."
    VALIDATION_UNKNOWN_FIELD = "This field is not allowed."
    VALIDATION_INVALID_TYPE = "This value has the wrong type."
    VALIDATION_TOO_SHORT = "Use at least {} characters."
    VALIDATION_TOO_LONG = "Use at most {} characters."
    VALIDATION_VALUE_TOO_SHORT = "This value is too short."
    VALIDATION_VALUE_TOO_LONG = "This value is too long."
    VALIDATION_CONTROL_CHARS = "Remove the control characters."
    VALIDATION_MARKUP_NOT_ALLOWED = "Remove < and >."
    VALIDATION_NAME_NEEDS_LETTER = "Use letters in the name."
    VALIDATION_EMAIL_INVALID = "Enter a valid email address, like name@company.com."
    VALIDATION_PASSWORD_TOO_SHORT = "Use a password of at least {} characters."
    VALIDATION_PASSWORD_TOO_LONG = "Use a password of at most {} characters."
    VALIDATION_PASSWORD_NEEDS_MIXED_CASE = "Mix upper and lower case letters."
    VALIDATION_PASSWORD_NEEDS_DIGIT = "Add a number."
    VALIDATION_PASSWORD_TOO_COMMON = "That password is too common."
    VALIDATION_PASSWORD_CONTAINS_EMAIL = "Do not use your email in the password."
    VALIDATION_PASSWORD_CONTAINS_NAME = "Do not use your name in the password."
    VALIDATION_PASSWORD_SAME_AS_CURRENT = "Choose a password you have not used here."
    VALIDATION_CODE_FORMAT = "Enter all 6 digits."
    VALIDATION_TIMEZONE_INVALID = "Choose a valid time zone."
    VALIDATION_CHOICE_INVALID = "Choose one of the listed options."
    VALIDATION_COMPANY_NOT_ALLOWED = "Individual accounts have no company name."
    VALIDATION_UUID_INVALID = "This id is not valid."
    VALIDATION_PHONE_NEEDS_PLUS = "Start the number with + and the country code."
    VALIDATION_PHONE_INVALID = "Enter a valid phone number, like +923001234567."
    VALIDATION_TIME_INVALID = "Use the format HH:MM, like 22:00."
    VALIDATION_QUIET_HOURS_PAIR = "Set both quiet hours times, or clear both."
    VALIDATION_LIST_INVALID = "Send a list."
    VALIDATION_NOTHING_TO_CHANGE = "Send at least one field to change."
    VALIDATION_PAGE_INVALID = "Use a page number of 1 or more."
    VALIDATION_PAGE_SIZE_INVALID = "Use a page size from 1 to {}."
    VALIDATION_DOMAIN_INVALID = "Enter a web domain like acme.com, without https:// or a path."
    VALIDATION_TEAM_REQUIRED = "Choose a team for team visibility."
    VALIDATION_TEAM_NOT_ALLOWED = "Only team visibility has a team."
    VALIDATION_TEAM_INVALID = "Choose one of your own teams."
    VALIDATION_DATETIME_INVALID = (
        "Use the exact date and time you were given, like 2026-11-09T12:00:00Z."
    )
    VALIDATION_COMPANY_INVALID = "Choose one of your companies."
    VALIDATION_MEMBER_INVALID = "Choose a member of this workspace."

    # -- Crm ----
    CRM_STAGE_NAME_TAKEN = "A stage with that name already exists."
    CRM_STAGE_LIMIT_REACHED = "A pipeline can have at most {} stages."
    CRM_STAGE_FIXED = "The Won and Lost stages cannot be renamed or deleted."
    CRM_STAGE_ORDER_INVALID = (
        "Send every stage once: the first open stage stays first, then the open stages, "
        "then Won, then Lost."
    )
    CRM_STAGE_IN_USE = "Move the deals out of this stage before deleting it."
    CRM_LAST_OPEN_STAGE = "A pipeline needs at least one open stage."
    CRM_CONTACT_EMAIL_TAKEN = "A contact with that email already exists."
    CRM_COMPANY_NAME_TAKEN = "A company with that name already exists."
    CRM_COMPANY_DOMAIN_TAKEN = "A company with that domain already exists."

    # -- Email ---- the texts of the emails the auth flows send
    EMAIL_VERIFY_CODE_SUBJECT = "Your Nudge verification code"
    EMAIL_VERIFY_CODE_BODY = (
        "Your code is {}. It expires in 10 minutes. If you did not ask for it, ignore this email."
    )
    EMAIL_REGISTER_EXISTING_SUBJECT = "Someone tried to sign up"
    EMAIL_REGISTER_EXISTING_BODY = (
        "Someone tried to create a Nudge account with this email. If it was you, sign in or "
        "reset your password at {}. If it was not you, you can ignore this email."
    )
    EMAIL_RESET_LINK_SUBJECT = "Reset your Nudge password"
    EMAIL_RESET_LINK_BODY = (
        "Reset your password here: {}. The link works once and expires in an hour. "
        "If you did not ask for it, ignore this email."
    )
    EMAIL_PASSWORD_CHANGED_SUBJECT = "Your Nudge password was changed"
    EMAIL_PASSWORD_CHANGED_BODY = (
        "Your Nudge password was changed. If this was not you, reset it now at {}."
    )

    # -- Email layout ---- the sentences of the designed (HTML) emails; templates only insert values
    EMAIL_BRAND_NAME = "Nudge"
    EMAIL_GREETING = "Hi {},"
    EMAIL_CODE_LABEL = "Your verification code"
    EMAIL_FOOTER_AUTOMATED = "This email was sent automatically. Replies are not monitored."
    EMAIL_FOOTER_BRAND = "{} © {}"
    EMAIL_VERIFY_HEADING = "Verify your email"
    EMAIL_VERIFY_INTRO = "Enter this code in Nudge to finish creating your account."
    EMAIL_VERIFY_VALID = "The code expires in 10 minutes."
    EMAIL_VERIFY_NOT_YOU = "If you did not ask for it, you can ignore this email."
    EMAIL_EXISTING_HEADING = "Someone used your email to sign up"
    EMAIL_EXISTING_INTRO = "Someone tried to create a Nudge account with this email address."
    EMAIL_EXISTING_BUTTON = "Go to sign in"
    EMAIL_EXISTING_LINK_LABEL = "Or open this link in your browser:"
    EMAIL_EXISTING_NOT_YOU = "If it was not you, you can ignore this email."
    EMAIL_RESET_HEADING = "Reset your password"
    EMAIL_RESET_INTRO = "Use the button below to choose a new password for your Nudge account."
    EMAIL_RESET_BUTTON = "Reset password"
    EMAIL_RESET_LINK_LABEL = "Or copy this link into your browser:"
    EMAIL_RESET_VALID = "The link works once and expires in an hour."
    EMAIL_RESET_NOT_YOU = "If you did not ask for a reset, you can ignore this email."

    # -- Cli ---- management commands
    CLI_COMMAND_REFUSED = (
        "'{}' is disabled. The nudge schema comes from docs/nudge_schema_v3_1_no_pgvector.sql "
        "and is never changed or emptied by Django."
    )

    CLI_DEV_ONLY_SETTINGS = (
        "{} only runs with the development settings (config.settings.dev), not with '{}'."
    )
    CLI_DEV_ONLY_DEBUG = "{} only runs with DEBUG on."
    CLI_DEV_ONLY_DATABASE = "{} only runs on the development database '{}', not on '{}'."
    CLI_SEED_SUMMARY = "Demo workspace '{}': {} stages, {} companies, {} contacts."
    CLI_SEED_CREATED = "Sign in with {} and the password {} (shown only now, it is not stored)."
    CLI_SEED_EXISTS = (
        "The demo workspace already exists (owner {}). Nothing was duplicated and the password "
        "is unchanged. Use --reset-password for a new one."
    )
    CLI_TEST_EMAIL_SUBJECT = "Nudge test email"
    CLI_TEST_EMAIL_BODY = "This is a test message from Nudge. If you can read it, sending works."
    CLI_TEST_EMAIL_SENT = "Test email sent to {} (backend {})."
    CLI_PREVIEW_EMAIL_WRITTEN = "Preview of '{}' written to {}. Open the file in a browser."
    CLI_PREVIEW_EMAIL_FAILED = "The preview could not be written."
    CLI_TEST_EMAIL_FAILED = "Sending failed. Check the EMAIL_* settings; the log has the reason."
    CLI_SEED_NEW_PASSWORD = "New password for {}: {} (shown only now)."

    # -- Testdb ---- the pytest database builder
    TESTDB_REMOTE_HOST = "The test database must be on localhost or 127.0.0.1, not '{}'."
    TESTDB_UNSAFE_NAME = (
        "The test database name '{}' must end with '_test' and differ from the development "
        "database '{}'."
    )
    TESTDB_SQL_MISSING = "SQL file not found: {}. Check NUDGE_SCHEMA_SQL and NUDGE_SEED_SQL."
    TESTDB_TABLE_COUNT = "The test database has {} tables, expected {}. Check NUDGE_SCHEMA_SQL."
    TESTDB_FUNCTION_MISSING = "The test database has no {}() function. Check NUDGE_SCHEMA_SQL."
    TESTDB_LABEL_COUNT = "The test database has {} labels, expected {}. Check NUDGE_SEED_SQL."

    @property
    def code(self) -> str:
        """The code sent to the frontend: the member's name."""
        return self.name

    def render(self, *values: object) -> str:
        """The text with the {} filled in. Too few values raises IndexError, so a bug is loud, never
        silent."""
        return self.value.format(*values)
