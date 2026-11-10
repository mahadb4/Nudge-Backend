# Nudge backend

## What Nudge is
Mahad Baloch's SZABIST final year project and a possible startup. An AI sales-reply app: it reads customer
replies, sorts each into one of 9 reply types, drafts a reply using only approved company facts, and sends
nothing until the user approves (draft-only by default). Multi-tenant: every record belongs to an organization.
The React frontend is already built on mock data (D:\Desktop\Nudge-frontend). This repo is the Django REST backend.

## Stack
Django 5.2, DRF, PostgreSQL 18 (production must use the same major version), psycopg 3, django-environ,
argon2-cffi, PyJWT (access tokens, HS256), phonenumbers, redis, tzdata, drf-spectacular,
pytest-django. Python 3.13.9.

## Hard rules
- Answer in English only.
- Git: no git of any kind, not even read-only commands (status, diff, log). Never commit or push.
- Never run migrate or any command that changes the nudge database. The guard refuses migrate, makemigrations,
  flush, createcachetable and loaddata. Inspect nudge with read-only SELECTs only. Tests use nudge_test.
- The schema is frozen: docs/nudge_schema_v3_1_no_pgvector.sql is the source of truth, models are unmanaged
  (private to each repositories/models.py). Never add or change a table, column or index; propose it first.
- No magic strings: every sentence and error code is one line in `class Messages(StrEnum)` in common/messages.py
  (name = code sent to the frontend, value = English text, `{}` for values). Constants live in common/constants.py.
- Follow docs/ARCHITECTURE.md (layers, security) and docs/CODING_STYLE.md (file and class names).
  api -> services -> repositories -> database; constructor injection with Protocols; config/container.py wires.
- Ask the user before any decision the docs do not already settle. One step at a time: design, OK, tests, code.
- Do not open docs/reference/ (the student project) unless a style question comes up. Never read it in full.

## Style and scale rules (details in docs/CODING_STYLE.md)
Checked automatically by common/tests/test_architecture.py:
- Names: api/<entity>_api.py (<Thing>Api), dtos/<feature>_dtos.py, mappers/<entity>_mapper.py (plain functions),
  repositories/<entity>_repository.py, services/<entity>_service.py + <entity>_validator.py (format only, never the
  database), domain/ frozen dataclasses. Never one big dtos.py or mappers.py.
- Type hints on every function; statuses from http.HTTPStatus; no bare or blanket except; services raise only AppError.
- No wildcard cache operations; no mutable module-level state; every *ListApi uses the capped paginator (max 100).
- Timeouts on every query and external call (settings). Only repositories import repositories/models.py.
Review checklist (check by hand in every change):
- No unbounded query; big lists use keyset pagination; no N+1 (a query-count test per list endpoint).
- Filters and search only on indexed columns. Cache keys include the organization id; invalidate with versioned keys.
- Slow work (email, sync, ML, AI) sits behind an interface, never inside a transaction or, later, the request.
- Retryable writes are idempotent. Logs carry a request id and never passwords, tokens, codes or email bodies.
- Rate limit every public endpoint; auth endpoints fail closed. Stateless: nothing shared in process memory.

## Where things are
docs/: ARCHITECTURE.md (authority), BACKEND_PLAN.md (build order, auth design, decisions 9b, left-for-later 9c),
API_CONTRACT.md (every endpoint), CODE_MAP.md (plain-words tour), GAP_REPORT.md, QUESTIONS.md,
nudge_validation_spec_v3_1.md, nudge_normalization_v3_1.md, FRONTEND_SCAN.md, CODING_STYLE.md.
Code: config/ (settings, urls, container.py), common/ (messages, errors, constants, interfaces, validators, responses,
attempts, api, serializers, infra/, security/, health/, management/, testdb.py), apps/accounts, apps/crm, apps/audit
(api/ dtos/ mappers/ repositories/ services/ domain/ tests/). conftest.py rebuilds nudge_test per session.

## How to run
- `.venv\Scripts\activate`; `pytest`; `python manage.py check`; `python manage.py runserver`.
- CI-style checks, all four must be clean before a step is reported done (requirements-dev.txt, dev only):
  `pytest` (with the SQL path override below), `python manage.py check`, `pip-audit -r requirements.txt`,
  `ruff check` (line length 100, config in ruff.toml). `ruff format` is the formatter.
- Signing keys: SECRET_KEY, JWT_SIGNING_KEY and EMAIL_HASH_KEY need at least 64 random bytes. dev and prod settings
  refuse to start with a shorter key or a `change-me` placeholder (the error names the key, never prints it).
  Generate one with `python -c "import secrets; print(secrets.token_urlsafe(64))"`. Test settings use fixed keys.
- pytest drops and rebuilds nudge_test from NUDGE_SCHEMA_SQL + NUDGE_SEED_SQL (.env) each session.
  TEST_DATABASE_URL must be localhost and end with _test.

## Current status (updated 9 Nov 2026)
Done: Step 0-1; A1-A7; batch 1 review changes; profile; organization; deal stages; companies; contacts (list,
get, create, update with updated_at check, soft delete; q search, status/owner/company filters, ordering allowlist,
joins for owner and company names); `manage.py seed_demo`.
Endpoints: GET /health/, /auth/csrf/, /auth/me/, /organizations/current/, /deal-stages/, /companies/,
/companies/{id}/, /contacts/, /contacts/{id}/; POST /auth/register/, /verify/, /resend/, /login/, /refresh/,
/logout/, /password/, /reset/, /reset/confirm/, /deal-stages/, /companies/, /contacts/; PATCH /auth/me/,
/organizations/current/, /deal-stages/{id}/, /companies/{id}/, /contacts/{id}/; PUT /deal-stages/order/;
DELETE /deal-stages/{id}/, /companies/{id}/, /contacts/{id}/.
Email: real SMTP through the environment only (EMAIL_BACKEND, EMAIL_HOST, EMAIL_PORT, EMAIL_USE_TLS,
EMAIL_HOST_USER, EMAIL_HOST_PASSWORD, DEFAULT_FROM_EMAIL, EMAIL_TIMEOUT=10); dev defaults to the console backend; tests
never send. A mail failure is logged without secrets and the sign-up, resend, forgot-password and notice paths still
answer 202/204 (BACKEND_PLAN 9h). `python manage.py send_test_email you@example.com` (dev only) checks the settings.
Emails: the code, the sign-up notice and the reset email are multipart (text as before + designed HTML) from
common/email_templates/ via HtmlEmailSender (BACKEND_PLAN 9i); sentences stay in messages.py, values are autoescaped.
`python manage.py preview_email verify_code|register_existing|reset_link` (dev only) writes the HTML to a temp file;
`send_test_email you@example.com --kind <same kinds>` (dev only) sends that designed email with sample data.
seed_demo: `python manage.py seed_demo [--reset-password]`. Refuses unless settings are config.settings.dev, DEBUG
is on and the connected database is the dev database (DEV_DATABASE_NAME). The user runs it on the real nudge
database; Claude only tests it on nudge_test (the seeder is called directly, the command is tested to refuse).
Tests: 1408 passed (50 new for the HTML emails); ruff check, ruff format --check, manage.py check and pip-audit clean.
Mutation checks on contacts, visibility, the 409 "existing" reveal rule, seed_demo guard and idempotence: all caught
except equivalent mutants (guards repeated by a unique index).
In progress: waiting for the user's review of the email work. Next: wire the frontend (the user), then
opt-out/opt-in endpoints, deals (with version check) and the deals summary.
Left for later (BACKEND_PLAN 9c): request-id logging, connection pool, keyset pagination, Redis bucket, Django
common-password list. No trigram search index (it would be a schema change). Postponed after midterm: sessions
list, audit read, members, teams, invitations.
Midterm window ends 14 Nov: wiring 10-11 Nov, deals 12-13 Nov, 14 Nov buffer and demo.

## Decisions (settled)
- Messages: one line each in `Messages(StrEnum)`; error body {"code": "AUTH_BAD_CREDENTIALS", "detail": "<text>"};
  400 adds "fields" in the same shape. Codes are the member names.
- Email: the strict sender raises 503 on failure, the quiet sender (register, resend, forgot password, notices after a
  committed change) logs and answers as if sent, so replies never reveal whether an address exists. Never log the
  SMTP password, the login, the recipient or the body.
- Email verification: 6-digit code in the cache, 10 min, 5 wrong tries then locked, resend after 30 s. No table.
- Access token: JWT, algorithm HS256 (HMAC-SHA256, PyJWT used directly; no SimpleJWT), 10 min (user_id, sid, jti),
  in memory on the frontend. Every request also needs its session (sid) to be live: logout and password change
  end access tokens at once. Refresh: opaque value in an HttpOnly
  cookie nudge_refresh (Path=/api/v1/auth/, Lax), sha256 stored in user_sessions, rotated on use, reuse (or two requests with one value) revokes the session.
  Refresh never extends the session (1 day, or 30 days with keep me signed in).
- CSRF double submit on every cookie or auth POST endpoint. Passwords: Argon2, 8-128 characters, never trimmed.
- Same 202 and same limits for known and unknown emails; unverified users cannot sign in (403 AUTH_EMAIL_UNVERIFIED,
  only after the right password).
- Sign-up on a known UNVERIFIED address: only when its code has expired does the latest sign-up win (password, name,
  organization replaced, new code sent, audit user.register_replace). While the code is live, and for a VERIFIED
  address, nothing changes and only a notice is sent.
  Remaining risk is written in BACKEND_PLAN 9b point 7.
- Reset link: signed token '<user>-<expiry>-<hmac>' of the password hash and last sign-in, 1 hour, single use
  (a new password or a sign-in kills it). Reset signs every device out; password change signs out the others.
- Every API class is private by default (settings: AccessTokenAuthentication + IsAuthenticated); public ones
  set both lists to [] and a test lists them.
- snake_case JSON; account type "individual" | "business". Organization from X-Organization-ID, else the only membership.
- Tenancy: every tenant endpoint extends TenantApi (config/tenancy.py): the TenantContext (user, organization, role)
  is read from the memberships table on each request; header naming a foreign or malformed organization = 404, no
  header with several memberships = 400 TENANCY_ORGANIZATION_REQUIRED. read_roles/write_roles guard the methods and
  the service checks the role again. Tenant repositories extend TenantRepository: every method takes the context first.
- Contacts follow the companies pattern (TenantApi, TenantRepository, validator, DTOs, mapper, audit, updated_at
  check, shared owner/team rules in LinkService and visibility in link_repository.py). Email required and unique
  among live rows; a duplicate is 409 CRM_CONTACT_EMAIL_TAKEN with "existing" only if the caller can see it. The
  audit row for a contact never holds personal values ("changed" only). A private company's name is not shown.
- Companies: visible = Owner/Admin all, others organization-wide + own + own teams' rows; any member who can see a row
  may edit or delete it; PATCH needs updated_at (409 COMMON_VERSION_CONFLICT with current); name unique among live
  rows ignoring case (service check under an advisory lock), domain unique (index). Lists use common/pagination.py.
- Deal stages: Won and Lost fixed at the end, max 12, names unique ignoring case, the first open stage stays first,
  delete refused while any deal (even soft-deleted) uses the stage; every change locks the stage rows.
- New records default to Organization visibility; Manager behaves as Member. Audit log: Owner and Admin only.
- PostgreSQL 18 everywhere; no migrate, no Django admin; frontend limits win where stricter than the column.
- Assumed by Claude in A3/A4, please confirm (BACKEND_PLAN 9b): ids generated in Python (UUIDv7), Django's Argon2 hash
  format, UnitOfWork with email sent after commit, sessions after verify last 1 day, midterm limiter is a fixed
  window in the cache that fails closed, repositories use unmanaged ORM models.

## Update rule (for Claude)
Before you tell the user a step or feature is done, update the Current status and Decisions sections of
CLAUDE.md in the same turn (what was added, which endpoints or modules exist, which tests pass, what is
next). If a new decision is made, add it. Never finish a step without this update.
