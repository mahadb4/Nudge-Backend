# Backend plan

docs/ARCHITECTURE.md is the authority for style, layers, folder structure, dependency injection, error codes, REST conventions, rate limiting, testing and build order. This file only adds what ARCHITECTURE.md leaves open. If the two disagree, ARCHITECTURE.md wins.
The old 'core' app is now the common package.

Stack (fixed): Django 5.2, DRF (thin controller shell and field validation only), PyJWT (access tokens), PostgreSQL 18 (18.4 locally; production must use the same major version, decided 2 Nov 2026), psycopg 3, django-environ, phonenumbers, drf-spectacular, django-cors-headers, pytest-django.
Approved extras, all in requirements.txt from step 0:
- argon2-cffi, redis, tzdata (the IANA zone database; Windows has none built in), phonenumbers (already in the fixed stack).
- pip-audit, dev only, in requirements-dev.txt.

Schema (fixed): nudge_schema_v3_1.sql, 50 tables. No table, column or index is added or changed (Q-27).
Your answers to QUESTIONS.md (2 Nov 2026) are applied; (Q-n) tags show where.

- Python: 3.13.9 (Q-23).
- Validation spec: docs/nudge_validation_spec_v3_1.md is now cross-checked (Q-28). Section 6 lists every place where we differ from it and why.
- SQL and seed: still not in docs/. The spec's start guide (docs/nudge_backend_plan.md) says to copy nudge_schema_v3_1_no_pgvector.sql there; please also copy nudge_seed.sql. Until then the test setup reads them from D:\Downloads.
- docs/nudge_backend_plan.md (the start guide) is superseded where it disagrees with ARCHITECTURE.md or your answers:
  - email link -> 6-digit code;
  - apps accounts/organizations/email/ai -> ARCHITECTURE modules;
  - Python 3.12 -> 3.13.9;
  - inspectdb of all 50 tables -> only the tables each step needs.

## 1. Modules and tables

Layout and layers: ARCHITECTURE.md sections 1-3. common is a top-level package (not under apps/). Modules are under apps/.

Every module (each app, and common/health) has the same folders. File and class names are in docs/CODING_STYLE.md, which wins over ARCHITECTURE.md on names:
- `api/`: `urls.py`, `<entity>_api.py` with `<Thing>Api` classes (HTTP only).
- `dtos/`: `<feature>_dtos.py`: the strict request serializers and the small response dataclasses of one feature together.
- `mappers/`: `<entity>_mapper.py`: pure functions, only where the shape differs from the entity.
- `repositories/`: `interfaces.py` (Protocols), `models.py` (private unmanaged ORM models), `<entity>_repository.py`.
- `services/`: `<entity>_service.py`, `<entity>_validator.py` (format rules only, never the database), `interfaces.py` (what the module needs from other modules).
- `domain/`: `entities.py`, `enums.py`, `errors.py`, `defaults.py`. `cache/` (`<entity>_cache.py`) comes after the midterm. `tests/` (apps only).
The architecture test checks the folders, the file names, the class suffixes and the style and scale rules.
Messages: one `class Messages(StrEnum)` in common/messages.py, one line per message. The member name is the code sent to the frontend; the value is the English text with {} placeholders.

| Module | Tables | Phase |
|---|---|---|
| common | none | midterm |
| accounts | organizations, users, user_sessions, memberships, teams, team_members, invitations | midterm (invitations, team CRUD later) |
| crm | companies, contacts, deal_stages, deals, activities, lead_forms, lead_submissions | midterm (activities, lead_* later) |
| audit | audit_logs | midterm |
| mail | email_accounts, mailbox_access, email_threads, email_messages, message_recipients | later |
| ml | label_sets, labels, ml_models, evaluation_runs, predictions, prediction_labels, extractions, corrections, dataset_items, dataset_labels | later |
| workflow | category_settings, email_templates, company_facts, reply_drafts, follow_ups, notification_channels, notifications, call_logs | later |
| assistant | email_chunks, assistant_conversations, assistant_messages, assistant_citations | later |
| integrations | crm_connections, crm_stage_mappings, external_links | later |
| scheduling | meetings, prospect_calls | later, pending approval |
| outreach | sequences, sequence_steps, sequence_enrollments | later, pending approval |

Cross-module rules
- A module reads another module's data only through that module's service interface.
  - Example: crm asks accounts 'is this user an active member of organization X' through a MembershipQuery service.
  - It never reads the memberships table itself.
- Audit writes go through the AuditWriter Protocol (common/interfaces.py), implemented by the audit module. The container injects it.

## 2. Persistence (repositories)

- Repositories are the only code that touches the database. Each has a Protocol in repositories/interfaces.py and one implementation. They return domain entities (frozen dataclasses), never model instances or rows.
- Implementation inside a repository:
  - unmanaged Django models (managed = False, db_table = '<table>', field names = column names) for simple reads and writes;
  - the parameterized query runner in common/base_repository.py for keyset pages, grouped sums and conditional updates. Example: UPDATE ... WHERE version = %s RETURNING ...
  - Models are private to the repository package. Services and controllers never import them.
- Ids (Q-23, Python 3.13): UUIDv7 generated in Python by the IdGenerator (common/infra/ids.py), not by the database default.
  - Reason: a session's refresh value contains the session id and is hashed before the row exists, so the id must be known first.
  - The database function nudge_uuid_v7() stays as the default for raw SQL. With Python 3.14 the generator can call uuid.uuid7().
- Smallint codes: IntEnum in each module's domain/enums.py, exactly the codes in nudge_db_design_v3_1.md. Mappers turn them into the lowercase strings of API_CONTRACT.
- Composite tenant FKs are enforced by the database at commit. Services check that referenced ids belong to the tenant first (through repositories), so the client gets 400/404, not a 500.
- Tenant filter: every tenant repository method takes TenantContext (or organization_id) as its first argument and filters by it. A repo test per query proves isolation.
- No migrations (Q-7):
  - `migrate` is never run on the nudge database; a guard refuses it.
  - No Django admin, sessions or messages apps; no PermissionsMixin.
  - Whether django.contrib.auth stays installed is decided in the step 5 design. Authentication is our own JWT class in common/security, hashing is argon2-cffi behind PasswordHasher, so contrib.auth may not be needed at all.
- Test database (Q-13):
  - pytest builds it from nudge_schema_v3_1_no_pgvector.sql + nudge_seed.sql with --nomigrations.
  - Transaction-rollback tests only (audit_logs refuses TRUNCATE).
  - SET CONSTRAINTS ALL IMMEDIATE at the start of each repo test.
  - A drift test compares models with information_schema and checks there are exactly 50 tables.
- Default stages at sign-up: created by the accounts service through the crm stage service interface, with the 7 rows of nudge_create_default_stages().

## 3. Build order

Reordered 9 Nov 2026: authentication and authorization come first, as one slice, before anything else.
The midterm window ends 14 Nov 2026. One step at a time, each reviewed by you.
Order inside a step: design shown to you, Protocol first, tests, repository, service, controller, run tests.
The frontend task (Q-29) starts when the auth endpoints pass their tests (after A6).

Done
| Step | Work | Check |
|---|---|---|
| 0 | Skeleton: settings split, django-environ, .env.example, pinned requirements, pytest.ini, module packages, cache from CACHE_URL | `manage.py check`; pytest; pip-audit clean |
| 1 | Database settings (CONN_MAX_AGE=60); nudge_test rebuilt each session from the SQL files with SET CONSTRAINTS ALL IMMEDIATE; builder refuses non-local hosts and names not ending _test; migrate guard (migrate, makemigrations, flush, createcachetable, loaddata) | 49 tests |
| A1 | 2a-lite: messages (auth codes only), errors, constants (plain functions), interfaces, text, validators, infra/clock, responses with the exception handler, JSON 400/403/404/500 and CSRF-failure views, no-store middleware for /api/, test fakes, architecture test | 335 tests in total (with A2) |
| A2 | Health endpoint GET /api/v1/health/ (HealthApi, HealthService, HealthRepository); unknown /api/v1/ paths are JSON 404 | 200 / 503 / 405 / 404 tests; curl against nudge |

Slice A: authentication and authorization (midterm, in this order)
| Step | Work | Check |
|---|---|---|
| A3 | Done 9 Nov. accounts entities and repositories (users, organizations, memberships, user_sessions); crm StageService seeds the 7 default stages; audit AuditService writes audit_logs | Repository tests on nudge_test incl. tenant isolation, duplicate-email race, conditional refresh rotation, parity with nudge_create_default_stages(), append-only audit_logs |
| A4 | Done 9 Nov. Register + email code + verify (signs the user in) + resend + csrf; RegistrationService, VerificationService, SessionService, MeService, UserValidator; strict request DTOs; attempt limiter | 40 HTTP tests, 60+ service unit tests, mutation-checked (CSRF, transaction, lockout, unknown-user) |
| A5 | Login + refresh + logout + me + csrf | Unverified + right password -> 403; cookie flags; remember 30 d vs session cookie 1 d; access 10 min; rotation; reuse -> 401 and session revoked; same 401 for unknown email and wrong password; attempt limit -> 429 with Retry-After |
| A6 | Forgot password + reset + password change | 128 accepted, 129 refused; change revokes other sessions; reset link single use and 1 hour; reset revokes all sessions; same 202 for unknown email |
| A7 | Authorization: Role checks, TenantContext from X-Organization-ID or the only membership, permission checks in controllers, tenant-scoped repository base | Other organization's id -> 404; no header + 2 memberships -> 400; Member refused on Owner/Admin endpoints; every tenant repository method takes TenantContext |

Kept in slice A: JWT access token, rotating refresh cookie, CSRF, Argon2, a simple attempt limit (fixed window in the cache; in-memory is acceptable for now), the same response for known and unknown emails, an audit write for every auth event.

Slice B: after A (midterm if time allows)
| Step | Work |
|---|---|
| B1 | Profile and organization (read, update), members read, teams read |
| B2 | Deal stages |
| B3 | Companies |
| B4 | Contacts (with opt-out) |

Postponed until after the midterm
- Full token bucket and Redis store (ratelimit.py, step 2b), X-RateLimit-* headers.
- Cursor pagination and the full query parser (pagination.py, query.py). Slice B lists use simple offset pages.
- Sessions list screen (GET/DELETE /auth/sessions/).
- Audit log read endpoint (GET /audit-logs/). Audit writes stay in slice A.
- Deals (CRUD, move, summary).
- Then the rest of the old steps 9-10: tenancy and N+1 sweep, API docs check, seed_demo, production settings, psycopg-pool, database roles.

Midterm schedule (proposed)
| Date | Target |
|---|---|
| 9 Nov | A1, A2 (done), CLAUDE.md, auth slice design |
| 10 Nov | A3, A4 |
| 11 Nov | A5 |
| 12 Nov | A6, A7; frontend auth hookup can start |
| 13 Nov | B1-B4 as far as time allows |
| 14 Nov | Buffer, demo run-through, end of midterm window |

The architecture test (ARCHITECTURE 10) runs from A1 and grows with each step. It checks:
- services do not import django, rest_framework or psycopg;
- api does not import repositories;
- repositories do not import services;
- the framework-free common modules do not import django, rest_framework or psycopg;
- no string literal is passed to an error class;
- no message-code literal outside common/messages.py (prefixes taken from all_messages()).

## 4. Auth design

Tokens, flows and other protections: ARCHITECTURE section 9. Additions below.

- Access JWT: HS256 with JWT_SIGNING_KEY, built by the TokenSigner implementation in common/security (PyJWT directly).
  - Every authenticated request also checks that the token's sid points at a session with revoked_at IS NULL and expires_at > now(): one primary-key lookup.
  - A failure -> 401 AUTH_ACCESS_TOKEN_INVALID.
- Refresh value: '<session uuid>.<256-bit secret>'. Only sha256 of the whole value is stored.
  - Cookie nudge_refresh, Path=/api/v1/auth/, HttpOnly, Secure outside local dev, SameSite=Lax.
  - 'Keep me signed in': Max-Age 30 days, expires_at +30 d. Otherwise a session cookie and expires_at +1 d (Q-9).
  - A wrong secret for a live session id -> revoke that session; 401 AUTH_SESSION_INVALID.
- No token blacklist table: user_sessions does that job. SimpleJWT was removed from the stack on 9 Nov 2026.
- CSRF (common/security): double submit for login, verify, refresh, logout, register, resend, reset and reset confirm.
  - GET /auth/csrf/ sets the csrftoken cookie.
  - CSRF_TRUSTED_ORIGINS = the frontend origin.
  - Failure -> 403 AUTH_CSRF_FAILED.
- Verification code (Q-1), stored through the Cache Protocol:
  - HMAC of the code, 10 min TTL, try counter (5);
  - the resend_email bucket gives the 30 s rule;
  - resend deletes the old code.
- Reset link: signed, 1 hour, single use (the signature covers the password hash and last_login). The token fits /^[\w-]{4,200}$/.
- Passwords (Q-2): 8-128 characters, Argon2 through PasswordHasher. The hasher has dummy_verify() for equal timing on unknown emails.
- Unverified users (Q-8): 403 AUTH_EMAIL_UNVERIFIED only after a correct password.
- Google, Microsoft and SSO: not in the midterm; the frontend hides the buttons (Q-3).
- Demo (Q-4): `manage.py seed_demo`, dev and staging only (refuses with DEBUG False or prod settings).
- Rate limits: common/ratelimit.py token bucket. Policies are in common/constants.py and in API_CONTRACT section 9.
  - Store: Redis when CACHE_URL is redis://. One Lua script per check reads Redis TIME itself, so no app clock is involved.
  - Otherwise the in-memory store (dev, one process), which reads the injected Clock.
  - Prod refuses the in-memory store.
  - Each RatePolicy has a critical flag. If the store raises:
    - critical policies (login_email, login_ip, resend_email, verify_ip, register_ip, reset_email, reset_ip, reset_confirm_ip; password_change_user proposed) fail closed with ServiceUnavailable (503 COMMON_SERVICE_UNAVAILABLE);
    - api_user fails open and logs a warning with the policy name.
  - Email keys use HMAC-SHA256 of the normalised email with a server key, not plain sha256, so stored keys cannot be reversed by hashing known addresses.
- Organization (Q-22):
  - Controllers build TenantContext(user_id, organization_id, role) from X-Organization-ID, or from the only active membership, through the accounts membership service.
  - No header and several memberships -> 400 TENANCY_ORGANIZATION_REQUIRED.
  - Not a member -> 404 COMMON_NOT_FOUND.
- Roles (common/permissions.py, used by controllers):
  - Owner and Admin: organization settings, stages, members, audit log (Q-19), opt-out removal (Q-17).
  - Member: CRUD on visible records.
  - Manager = Member (Q-20).
- Errors, pagination, query parsing, field names: API_CONTRACT section 0 (UPPER_SNAKE codes from the Messages enum, fields envelope, offset and cursor shapes, whitelists, snake_case).

## 5. Performance rules

- Every list paginates (offset for small lists, keyset cursor for large), except deal stages (at most 12) and the user's own sessions.
- Repositories fetch related data with joins (select_related or one SQL join), and counts and per-currency sums with one grouped query per page. No per-row queries.
- Sort orders match existing indexes:
  - companies: lower(name) (ix_companies_2)
  - contacts: lower(last_name), lower(first_name) (ix_contacts_2)
  - deals per stage: (stage_id, id) (ix_deals_1)
  - audit: created_at desc, id (ix_audit_logs_1)
- Search: parameterized ILIKE, q 2-100 characters, no new indexes (Q-27). Debouncing is the frontend's job (about 300 ms, cancel the older request).
- Query-count caps in api tests for every list endpoint (50 rows).
- psycopg 3 pool, CONN_HEALTH_CHECKS = True. Stateless API: no server memory between requests except the dev-only in-memory rate store.

## 6. Server-side security list

Everything the frontend checks is checked again on the server.
- The frontend limit wins when stricter (Q-30); column limits are in brackets.
- Each failure carries the validation.* code shown (texts in common/messages.py).
- Cross-checked against docs/nudge_validation_spec_v3_1.md. The table 'Differences from the validation spec' at the end of this section lists every rule where we differ.

Text (spec rule 'reject the NUL character and control characters'; the frontend strips them):
- First, CRLF and CR become LF.
- Then any C0/C1 control character or DEL (tab and newline allowed in multi-line fields only) -> VALIDATION_CONTROL_CHARS. Includes NUL, which PostgreSQL cannot store.
- Then common/text.py clean() or clean_multi():
  - Unicode NFC;
  - remove zero-width, soft hyphen, bidi override and isolate characters;
  - single-line text: collapse whitespace and trim.
- Change from the step 2 design: controls are rejected, not stripped. The frontend strips them before sending, so only a hostile client meets this error.
Length is checked after cleaning; over-long input is refused, never cut. Passwords are never cleaned. They are refused if they contain C0 controls or DEL (VALIDATION_CONTROL_CHARS).

| Field | Rule | Codes |
|---|---|---|
| any required field | present and not blank | VALIDATION_REQUIRED |
| unknown field or query parameter | refused | VALIDATION_UNKNOWN_FIELD |
| wrong JSON type | refused | VALIDATION_INVALID_TYPE |
| email | trim, lowercase, <= 254, local <= 64, validate.ts ASCII regex, no '..', no edge dots, TLD letters >= 2 | VALIDATION_EMAIL_INVALID, VALIDATION_TOO_LONG |
| password (set) | 8-128 (Q-2); upper and lower; digit; no control chars; not common (frontend list + Django's 20k list, injected); not containing the email local part (>= 4 chars) or a name word (>= 4 letters); differs from current | VALIDATION_PASSWORD_TOO_SHORT, VALIDATION_PASSWORD_TOO_LONG, VALIDATION_CONTROL_CHARS, VALIDATION_PASSWORD_NEEDS_MIXED_CASE, VALIDATION_PASSWORD_NEEDS_DIGIT, VALIDATION_PASSWORD_TOO_COMMON, VALIDATION_PASSWORD_CONTAINS_EMAIL, VALIDATION_PASSWORD_CONTAINS_NAME, VALIDATION_PASSWORD_SAME_AS_CURRENT |
| password (login) | present, <= 128 | VALIDATION_REQUIRED, VALIDATION_PASSWORD_TOO_LONG |
| person name (user) | 2-80 [150], a letter, no < > | VALIDATION_TOO_SHORT, VALIDATION_TOO_LONG, VALIDATION_NAME_NEEDS_LETTER, VALIDATION_MARKUP_NOT_ALLOWED |
| contact first / last name (Q-14) | first 1-80 with a letter; last 0-80, with a letter if not empty; no < > | same |
| company and workspace name (Q-16) | 2-120 [150], no < >; company unique per organization ignoring case | same; CRM_COMPANY_NAME_TAKEN |
| company domain (Q-16) | lowercase host name (letters, digits, hyphens, at least one dot, TLD letters), <= 253, unique among live rows. A URL is refused (the spec would keep only the host; see the differences table) | VALIDATION_DOMAIN_INVALID; CRM_COMPANY_DOMAIN_TAKEN |
| contact email (Q-14) | required for manual creation; unique among live rows | VALIDATION_REQUIRED; CRM_CONTACT_EMAIL_TAKEN |
| contact title | <= 80 [100] | VALIDATION_TOO_LONG |
| industry | <= 80 | VALIDATION_TOO_LONG |
| phone (Q-12) | optional; must start with '+'; phonenumbers valid; stored E.164 | VALIDATION_PHONE_NEEDS_COUNTRY_CODE, VALIDATION_PHONE_INVALID |
| deal name | 2-80 [150], no < > | as names |
| amount (Q-18) | required decimal, <= 2 places, > 0, < 1e12; no exponent, NaN, Infinity | VALIDATION_AMOUNT_INVALID |
| currency (Q-11) | ISO 4217 active list | VALIDATION_CURRENCY_INVALID |
| expected_close_date | real date <= 2100-12-31; not past on create | VALIDATION_DATE_INVALID, VALIDATION_DATE_IN_PAST |
| lost_reason (Q-18) | required for a lost stage; 1-200 | VALIDATION_REQUIRED, VALIDATION_TOO_LONG |
| stage name (Q-5) | 1-40 [60], no < >, unique ignoring case, <= 12 stages, Won/Lost fixed | CRM_STAGE_NAME_TAKEN, CRM_STAGE_LIMIT_REACHED, CRM_STAGE_FIXED |
| time zone | in zoneinfo.available_timezones() (needs tzdata on Windows) | VALIDATION_TIMEZONE_INVALID |
| quiet hours | both or neither, HH:MM; end may be earlier than start (overnight, spec) | VALIDATION_QUIET_HOURS_PAIR, VALIDATION_TIME_INVALID |
| account type (register) | "individual" or "business" (lowercase on the wire; capitalised values are refused). Business: company required, 2-120, no < >. Individual: company absent or empty; organization name = the user's cleaned full_name | VALIDATION_CHOICE_INVALID, VALIDATION_REQUIRED, VALIDATION_COMPANY_NOT_ALLOWED |
| team_id with visibility team | a team of the organization that the caller belongs to (spec) | VALIDATION_TEAM_INVALID |
| ip_address (sessions, audit) | from the socket, or from X-Forwarded-For only when the request comes from a configured trusted proxy (spec) | none (server-set) |
| device_name | derived from User-Agent, cleaned, cut to 100 (server-set, so cutting is allowed) | none |
| verification code (Q-1) | exactly 6 ASCII digits | VALIDATION_CODE_FORMAT |
| reset token | /^[\w-]{4,200}$/ before lookup | AUTH_INVALID_TOKEN |
| uuid in body / path | valid UUID and in the tenant | VALIDATION_UUID_INVALID (body), COMMON_NOT_FOUND (path) |
| enums | exact value from the list | VALIDATION_CHOICE_INVALID |
| q | 2-100 after clean | VALIDATION_QUERY_TOO_SHORT, VALIDATION_QUERY_TOO_LONG |
| sort | from the allowed list | VALIDATION_SORT_INVALID |
| page, page_size | page >= 1; page_size 1-100 | VALIDATION_PAGE_INVALID, VALIDATION_PAGE_SIZE_INVALID |
| cursor | decodes to (sort value, uuid) of the right types | VALIDATION_CURSOR_INVALID |
| later fields (subject, body, fact, template, reject reason, confidence bar, chat, CSV) | as listed before: subject 2-200 single line; body 1-5000 approve, 5-5000 compose; fact name 2-60, value 5-200; template name 2-80, body 5-5000; reject reason from 6; bar 60-99; chat <= 500; CSV <= 1 MB, <= 1000 rows, strict UTF-8, formula cells refused on import and prefixed on export | added to messages.py when built |

Differences from the validation spec (docs/nudge_validation_spec_v3_1.md). In every row we keep our rule unless the last column says otherwise.
| Field | Spec | Ours | Why |
|---|---|---|---|
| all text | reject NUL and control characters | same (changed from stripping) | spec |
| users.email | Django EmailValidator; reject 'already in use' at sign-up | validate.ts ASCII rule; sign-up answers the same 202 for a used email | Same rule as the frontend. Saying 'already in use' would reveal accounts (ARCHITECTURE 9). Needs your OK because the spec cites an SRS message |
| users.password | >= 8 with letters and numbers; max open (64+ suggested) | 8-128, upper and lower, digit, common list, similarity | Q-2 and frontend rules (stricter) |
| password confirmation | both passwords must match | checked in the frontend only; the API receives one password | The confirm value is never sent |
| users.full_name | 2-150 | 2-80 | Q-30 |
| person-name rule, company-name rule | referenced 'below' but never defined in the spec | person: a letter, no < >; company: no < > | Gap in the spec |
| organizations.name (Individual) | optional; the service uses the user's name | the same; a company value is refused for Individual | Matches the spec; refusing makes misuse visible |
| users.phone, contacts.phone | country selector + number, valid for the chosen country | the frontend sends +<country code><number>; the server requires '+' and checks validity with phonenumbers | Equivalent: the country code carries the selected country |
| companies.visibility, contacts, deals | default 1 Private | default 3 Organization | Q-20 |
| companies.name | required, max 150 | 2-120 and unique ignoring case | Q-16, Q-30 |
| companies.domain | accept a pasted URL, keep only the host | refuse a URL (VALIDATION_DOMAIN_INVALID) | Your instruction (b). The frontend has the same rule. Revisit if users paste URLs |
| contacts.email | optional | required for manual creation | Q-14 |
| contacts.email duplicate | reject and show the existing contact | 409 with existing {id, name} only if the caller can see it | Visibility: a private contact must not leak |
| contacts.job_title | max 100 | max 80 | Q-30 |
| deal_stages.name | max 60 | max 40 | Q-5, Q-30 |
| deal_stages.outcome | at least one Won and one Lost | exactly one Won and one Lost, fixed at the end | Q-5 (stricter) |
| deal_stages.position | gap-free, rewritten in one transaction | same | spec |
| deals.title | max 150; a duplicate name is only a warning | 2-80; a duplicate name adds "warnings": [CRM_DEAL_NAME_EXISTS] to the 201/200 body | Q-30; the warning form needs your OK (open point 10) |
| deals.amount | optional, >= 0, decimals by currency (ISO minor units), <= 16 integer digits | required, > 0, decimals <= min(2, currency minor units), < 1e12 | Q-18. The minor-unit rule is adopted: JPY 0 decimals. numeric(18,2) cannot store 3-decimal currencies (BHD, KWD and others) beyond 2 places. Note: the spec says PKR has 0 decimals, but ISO 4217 gives PKR 2; we follow ISO |
| deals.currency | ISO 4217 from a list; default from the organization's currency | ISO 4217 from a list; no organization currency column, so the form defaults from the browser locale | Q-11 |
| deals.expected_close_date | past allowed (shown overdue) | not in the past on create; past allowed on edit | Q-18 (frontend rule) |
| teams.name | required, unique ignoring case, max 80 | same (when team CRUD is built) | spec |
| teams, team_members phase | Midterm | read-only GET /teams/ in the midterm; team CRUD later | Answer (c): the midterm scope you set has no team screen. Visibility team needs the tables, so they are read |
| memberships.role | only an Owner grants Owner; last Owner cannot be removed | same (later endpoints) | spec |
| ip_address | from X-Forwarded-For of a trusted proxy only | same (TRUSTED_PROXIES setting) | spec |

Authentication and sessions
- Same status, body and similar timing for known and unknown emails (dummy hash check).
- Buckets per API_CONTRACT section 9; the verify try counter per code.
- Codes and tokens are stored only as hashes, expire and are single-use.
- Rotation with reuse detection. Revocation on logout, password change and reset.
- Never log passwords, codes, tokens, cookies or email bodies. Failed logins are audited with the email hash only.

Tenancy and roles
- Tenant filter in every repository query; other organizations' ids -> 404.
- Role checks in controllers through common/permissions.py.
- Visibility default Organization (Q-20).
- Later:
  - at least one active Owner;
  - automatic sending only for categories in mode 3 after 50 approvals (Q-6);
  - organizations.automation_paused_at blocks automatic actions.

Opt-out enforcement (every send)
- One gate in the workflow service, assert_sendable(tenant, recipients). Every send path calls it: approve review, approve follow-up, compose, automatic send, sequence step, and the sender worker right before the provider call.
- Any To or Cc address matching a contact (soft-deleted included) with opted_out_at -> 409 WORKFLOW_RECIPIENT_OPTED_OUT; audit reply_draft.blocked_opt_out.
- An opt_out prediction sets opted_out_at (creating the contact if needed, source 4).
- Removing an opt-out: Owner and Admin, audited (Q-17).
- Midterm: the opt-out endpoints and audit rows. The gate comes with the first send path.

Record changed (409 COMMON_VERSION_CONFLICT, body includes current)
- deals: version.
- companies and contacts: updated_at (Q-15).
- reply_drafts: status-guarded transitions; undo while now < send_after (10 minutes, Q-24).

Transport and configuration
- HTTPS and HSTS in production; nosniff; X_FRAME_OPTIONS DENY; strict Referrer-Policy.
- CORS: FRONTEND_URL only, credentials on.
  - Allowed headers: authorization, content-type, x-csrftoken, x-organization-id.
  - Exposed headers: retry-after, x-ratelimit-limit, x-ratelimit-remaining.
- Body limit 1 MB; strict Content-Type (application/json).
- API docs public only in DEBUG, staff only in production (Q-21).
- Secrets in environment variables only. pip-audit before release.

Audit actions (constants in common/constants.py; the DB trigger refuses UPDATE, DELETE and TRUNCATE)
- Midterm:
  - user.register, user.email_verify, user.login, user.login_failed, user.logout, user.password_change, user.password_reset_request, user.password_reset, user.profile_update
  - session.revoke, organization.update
  - deal_stage.create/update/reorder/delete
  - company.create/update/delete
  - contact.create/update/delete/opt_out/opt_in
  - deal.create/update/stage_change/delete
- Later: membership.*, invitation.*, mailbox.*, reply_draft.*, fact.*, template.*, automation.*, contact.import, *.export.

## 7. Midterm demo

Sign up -> verify code (console email backend) -> sign in -> profile -> stages -> companies, contacts, deals with a 409 on a stale edit -> audit log as Owner -> /api/v1/docs/ -> /api/v1/health/. `manage.py seed_demo` for a filled workspace.

## 8. Frontend changes

A separate task, after step 6 (Q-29). Same git rules.
1. Call GET /auth/csrf/ before the first unsafe request.
2. Boot with POST /auth/refresh/ instead of GET /auth/me/; keep the access token with setAccessToken().
3. On 401 AUTH_ACCESS_TOKEN_INVALID: refresh once and retry; on 401 AUTH_SESSION_INVALID: sign out.
4. Login and verify act on body.code (AUTH_BAD_CREDENTIALS, AUTH_INVALID_CODE, AUTH_CODE_ATTEMPTS_EXCEEDED, AUTH_EMAIL_UNVERIFIED -> /verify and resend). A login 401 must not trigger onUnauthorized.
5. Send timezone in register.
6. Send X-Organization-ID once there is more than one workspace.
7. Map snake_case fields to the TS types in src/api/.
8. Deals use stage_id and outcome; Settings > Deal stages calls the stage endpoints.
9. Contact form: first and last name; email required (Q-14).
10. Owner selects use member ids.
11. Send version (deals) or updated_at (companies, contacts); handle 409 COMMON_VERSION_CONFLICT.
12. Money totals from /deals/summary/ per currency.
13. Hide demo texts when not isMock (Q-4).
14. Replace hardcoded user and workspace names with /auth/me/ data.
15. Hide Google, Microsoft and SSO buttons when not isMock (Q-3).
16. Verify resend countdown 42 s -> 30 s (Q-1).
17. Remove the 'Default currency' select; the deal form defaults currency from the browser locale and offers the ISO 4217 list (Q-11).
18. Phone fields: full country-code list in Profile; contact phone must start with '+' (Q-12).
19. Approve toast: 'Undo within 10 minutes' (Q-24).
20. Hide Settings > Audit log for Member and Manager (Q-19).
21. Hide 'Remove opt-out' for Member and Manager (Q-17).
22. 400 errors: read field names from body.fields (UPPER_SNAKE codes inside), not from the top-level keys (ARCHITECTURE 4).
23. Map error codes to ApiError codes in src/api/client.ts by body.code, not only by status.
24. Cursor lists use {"results", "next_cursor"}.
25. Search boxes: debounce about 300 ms and cancel the older request (ARCHITECTURE 8); send q only when 2+ characters.
26. Sign-up sends type lowercase ("individual" | "business"); the User type in src/store.ts reads lowercase type from /auth/me/ (display labels stay in the UI).

## 9. Open points from aligning with ARCHITECTURE.md

Points 1-7 approved on 2 Nov 2026. Points 8-11 are new and need your OK.
1. tzdata package. Approved.
2. Minimum q length: ARCHITECTURE asks for a minimum but gives no number. Default: 2.
3. Status 405 (wrong method) is not in ARCHITECTURE's status list. DRF returns it on its own. Default: keep 405 with code COMMON_METHOD_NOT_ALLOWED.
4. ServiceUnavailable (503) is not in the ARCHITECTURE error list. Default: add it as an AppError subclass for /health/.
5. Infra implementations (SystemClock, cache adapter, email sender) have no file in the ARCHITECTURE layout. Default: common/infra/ (clock.py in step 2; cache.py and email.py in step 4).
6. Rate-limit policies not given in ARCHITECTURE: approved in principle; the six values in API_CONTRACT section 9 still need your OK.
7. The 202 bodies of register, resend and reset carry {"code", "detail"} so the frontend can key on the code. ARCHITECTURE does not say whether success bodies may carry codes.
8. Sign-up with an email already in use: the spec says reject it with the SRS 'already in use' message. We answer the same 202 to avoid revealing accounts (ARCHITECTURE 9). Default: keep the 202, and the SRS wording moves to the 'someone tried to register' email.
9. password_change_user as a critical (fail-closed) policy. It is not in your list. Default: critical, since it guards current-password guessing.
10. Duplicate deal names (spec: warning, not error). Default: the 201/200 body gets "warnings": [{"code": "CRM_DEAL_NAME_EXISTS", "detail": "..."}].
11. Amount decimals follow ISO 4217 minor units, capped at 2 by the column (JPY 0; most others 2). Default: adopt. The spec's 'PKR 0 decimals' is not ISO; we use 2.

## 9b. Decisions made while building A3 and A4 (9 Nov 2026)

Defaults I chose where the docs were silent. Tell me to change any of them.
1. UnitOfWork Protocol (`atomic()` only). Registration and verification each run in one transaction; the email is sent after it commits.
2. Passwords use Django's Argon2 hash format (`argon2$argon2id$...`, about 100 characters), through the PasswordHasher Protocol.
3. Ids are generated in Python (see section 2).
4. Verification codes and sign-up/resend limits are keyed by the HMAC of the email (EMAIL_HASH_KEY), so a known and an unknown address behave identically, including the 5-try lock.
5. After verifying, the session is a 1-day session with a session cookie (`remember` = false). "Keep me signed in" belongs to the login form (A5).
6. A second sign-up or resend for the same address within 30 seconds is refused for every address, known or not.
7. Sign-up with a known address (changed 9 Nov 2026, twice; user decisions; fixes an account pre-hijack):
   - Known, unverified address whose verification code has EXPIRED (more than 10 minutes since the last code): the latest sign-up wins. In one transaction the password hash, name, timezone, organization name, type and timezone are replaced, `user.register_replace` is audited (SYSTEM actor, email HMAC only), and a new code is emailed. The update only applies while `email_verified_at` is still null.
   - Known, unverified address whose code is still LIVE: treated exactly like a verified address. Nothing changes, no code is invalidated, the owner gets the "someone tried to sign up" notice, and the response, the slow hashing work and the audit row (`user.register_existing`) are the same.
   - Known, verified address: nothing is changed; the notice is sent and `user.register_existing` is audited.
   - All cases answer the same 202 as a new address.
   - Remaining risks, honestly:
     1. An attacker who signs up with the victim's email FIRST gets a live code mailed to the victim, and for 10 minutes the victim's own sign-up cannot replace it. If the victim types that code (the attacker's), the account has the attacker's password. The victim's mailbox is the only place the code goes, the email says nothing about who asked, and the sign-up is limited to 1 per 30 s per email and 10 per hour per IP. Later hardening: say in the code email which name the sign-up used, and force a password reset on the first sign-in after a verification whose sign-up was not the latest.
     2. An attacker can keep an unverified address "reserved" by re-registering it every 10 minutes (costing them one email to the victim each time). A victim who gets locked out this way can use "forgot password" (works for unverified accounts, does not verify the email) and then the 6-digit code from resend.
8. The midterm limiter is a fixed window in the shared cache. The cache fails closed: if it is down, the endpoint answers 503. The token bucket and the Redis script stay postponed.
9. Access tokens are signed with PyJWT directly, because token expiry must follow the injected clock (tests move time). SimpleJWT was removed from requirements and the venv on 9 Nov 2026 (approved).
10. Repositories use unmanaged Django models (your original decision), private to each `repositories/models.py`.

## 9c. CODING_STYLE.md: what is applied, and what is left for later (9 Nov 2026)

Applied now (checked by common/tests/test_architecture.py unless marked review):
- Folder and file names, class suffixes, mappers as plain functions, frozen domain dataclasses, `<entity>_validator.py` that never touches the database.
- Type hints on every function, named HTTP statuses (`http.HTTPStatus`), no bare or blanket `except`, services raise only AppError subclasses.
- Scale rules that can be checked: no wildcard cache operations, no mutable module-level state, every `*ListApi` must use a capped paginator, cache-key functions in `cache/` must take `organization_id`, page-size cap of 100, per-query timeout (10 s) and email timeout (10 s) in settings.
- The remaining scale rules are a review checklist in CLAUDE.md.

Left for later (not cheap, or needs your OK):
| Item | Why it waits |
|---|---|
| Structured logging with a request id on every line | Needs a new middleware and a logging filter. Add before production; you were wary of unlisted middleware, so I did not add one unasked. |
| Connection pool (psycopg-pool) | Decided: at the production step. `CONN_MAX_AGE=60` until then. |
| Keyset pagination, the capped paginator `parse_page_params`, the query parser, `cache/` modules with versioned keys | Postponed with the lists (companies and contacts need offset pages first). The architecture test already refuses a `*ListApi` without the helper. |
| Redis token bucket and X-RateLimit-* headers | Postponed (see section 9b point 8). |
| Django's 20,000 common-password list | Only the frontend's 27 words and the sequence rules are checked today. |
| `device_name` from the User-Agent | Stored as empty until the sessions screen exists. |
| Synchronous email sending | A send to a real address takes longer than the "unknown address" path, so response time could reveal a known address. Goes away with the worker queue. |
| Idempotency keys | No retried write exists yet (sign-up and verify are repeat-safe by design). Needed with the first send path. |
| Search and filter index review | No filter exists yet; the rule applies from B3 (companies). |
| ruff (formatter and linter) | CODING_STYLE says PEP 8 so ruff can format. It is not installed and some lines exceed 88 characters. Needs your OK to add it to requirements-dev. |
| `docs/reference/` (the student project) | Not present in this repo, so it was never opened. |

## 9d. Assumptions made while building A5 and A6 (9 Nov 2026)

Defaults I chose where the docs were silent. Tell me to change any of them.
1. Refresh reuse is strict. A value that is not the session's current one burns the whole session. Two requests with the same cookie at once also burn it (one wins, one loses, both devices are signed out). So the frontend must send one refresh at a time, also across tabs (a shared lock, for example the Web Locks API). The alternative (refuse the loser but keep the session) would let a thief who races the owner stay in unnoticed.
2. Refresh never extends a session. The 'keep me signed in' flag is not stored; a session that lives 10 days or more counts as remembered (the two lifetimes are 1 and 30 days, so clock differences cannot flip it). Its cookie gets Max-Age = the time left.
3. The login lock counts every attempt per email, right or wrong (5 per minute). The cost: someone who knows your address can keep you from signing in for the rest of the minute. The IP limit (20 per minute) and the lock are fixed windows in the shared cache; both fail closed.
4. A bearer token is checked with one lookup, the session. It does not load the user, so a future "deactivate user" must revoke that user's sessions (login and refresh do check is_active).
5. Forgot password is not time-equal for known and unknown addresses: only a known address sends an email. Same 202 and same limits, but a patient attacker with precise timing could tell. Fix later by sending the email after the response (queue).
6. A reset does not mark an unverified email as verified. Such an account still needs the 6-digit code.
7. Failed logins are audited with actor SYSTEM and a keyed hash of the address (details email_hmac), never the address or password. At most 20 per minute per IP can be written.
8. The device name of a session is the cleaned User-Agent, cut to 100 characters (the column size).
9. Logout needs only the cookie and CSRF (as in API_CONTRACT), not the bearer token.
10. GET /auth/me/ returns the oldest active membership as current until X-Organization-ID is added in A7.
11. Every API class is private by default (settings: AccessTokenAuthentication + IsAuthenticated). The DRF class sits in config/authentication.py (the composition root), because CODING_STYLE only allows `<entity>_api.py` files in api/.
12. Password change and reset send a "your password was changed" email that links to /sign-in. Reset and change both use a conditional UPDATE on the old hash, so two concurrent uses cannot both win.

## 9e. Assumptions made while building A7, profile, organization and stages (9 Nov 2026)

Defaults I chose where the docs were silent. Tell me to change any of them.
1. The class is called `TenantApi` (not TenantAPIView), because CODING_STYLE names classes `<Thing>Api`. It lives in `config/tenancy.py` next to `config/authentication.py`.
2. Membership and role are read on every tenant request (two small queries: memberships and organizations). A removed, suspended or demoted member is stopped on the next request. Caching this is a later optimisation.
3. A malformed or empty X-Organization-ID is 404, the same as a foreign one. The header is optional only when the user has exactly one active membership.
4. GET /auth/me/ and PATCH /auth/me/ accept the header too (so the frontend can ask "who am I in this workspace"); without it, the oldest membership is current.
5. Role checks happen twice on purpose: in `TenantApi` (before the body is read) and again in the service.
6. PATCH with an empty body is 200 and changes nothing (no audit row). Unknown fields are 400.
7. Organization and profile audit rows store field names only, never values. Stage audit rows store stage names (business labels, not personal data).
8. Deleting a stage is refused (409 CRM_STAGE_IN_USE) when ANY deal points at it, soft-deleted ones included, because the foreign key (RESTRICT) would otherwise fail with a 500. API_CONTRACT said "live deals"; this is stricter.
9. A new stage is inserted before the first Won or Lost stage; Won and Lost move up by one. Names are compared with casefold, and the database unique index (organization, lower(name)) is the second guard.
10. Stage name limit 40 (API_CONTRACT) although the column allows 60. At most 12 stages.
11. GET /organizations/ (the workspace switcher list) was not built; the `organizations` list in GET /auth/me/ already carries it.
12. The stage rules are tested through the real repository on nudge_test (service tests with a fake stage repository were skipped, because the rules depend on row locks and the unique index).

## 9f. Assumptions made while building companies (9 Nov 2026)

Defaults I chose where the docs were silent. Tell me to change any of them.
1. Any active member can create, edit and delete a company they can SEE (BACKEND_PLAN section 4: "Member: CRUD on visible records"). Visibility: Owner and Admin see every live row; everyone else sees organization-wide rows, rows they own and team rows of their own teams. A row you cannot see is 404 for read, update and delete.
2. Search (`?q=`) is a case-insensitive "contains" match on name, domain and industry within the organization's visible live rows. That uses the organization index but is not an index lookup on the text, so it scans one organization's companies. For midterm sizes that is fine; a trigram index would be a schema change and needs your OK.
3. The ordering allowlist is exactly `name` (default, case-insensitive, uses ix_companies_2) and `-created_at`. Contacts will reuse the same helper (`common/pagination.py`: page, page_size 1-100, q 2-100 characters, ordering, typed filters, unknown parameters are 400 and named).
4. The list runs five queries however many companies: count, page, owner names, contact counts, open-deal totals. A test fixes this. The detail endpoint uses the same code for one row.
5. `open_deal_count` / `open_value` count live deals in OPEN stages only, grouped per currency, never summed across currencies. `people_count` counts live contacts.
6. PATCH needs `updated_at` exactly as read (ISO 8601 with the offset). The write runs `WHERE updated_at = ?`, using the application clock for the new `updated_at` (a database `now()` would not change inside one transaction). A stale value is 409 COMMON_VERSION_CONFLICT with `current`. A PATCH that changes nothing returns 200 without writing or auditing.
7. Name uniqueness among live rows is a service check made under a per-organization advisory lock (the database only has a plain index). Domain uniqueness has the partial unique index as the final guard.
8. For `visibility: team` the caller must belong to the team, except Owner and Admin who may use any team of the organization. Moving away from team visibility drops the team automatically.
9. The owner of a company must be an active member of the organization; whoever creates a private company for a colleague still gets the reply even though they cannot read it afterwards.
10. Audit rows: `company.create`, `company.update` (details: label and `{field: {from, to}}`), `company.delete`. Values are business fields (names, domains, ids), no personal data.
11. Soft-deleting a company leaves its contacts and deals pointing at it (they keep working); no cascade.
12. The `Page` links (`next`, `previous`) are absolute URLs with the same filters and page size.
13. Part 1b: I also converted the `@staticmethod` helper in profile_service.py (written last run), five in total.

## 9g. Assumptions made while building contacts and seed_demo (9 Nov 2026)

Defaults I chose where the docs were silent. Tell me to change any of them.
1. Contacts reuse everything companies decided (9f): visibility, any member who can see a row may edit or delete it, `updated_at` check, contains-search without a new index.
2. The default order is last name then first name (ix_contacts_2). Contacts without a last name sort after those with one, because PostgreSQL sorts NULL last.
3. A contact's company is named only if the caller can see that company, so a private company's name does not leak through a visible contact; the company link must also be a visible company of this organization when you set it.
4. The 409 for a duplicate email adds `existing: {id, name}` only when the caller can see that contact. A private contact is not revealed (tested both ways).
5. Email cannot be cleared on PATCH for any contact (null is VALIDATION_REQUIRED). The contract limits this to manual contacts; every contact is manual until the CSV import exists.
6. The audit row of a contact write holds the label (the contact's name) and, for personal fields (names, email, phone, title), only the word "changed", never the values. Owner, company, visibility and team changes keep from/to.
7. Not built yet, though [midterm] in the contract: POST and DELETE /contacts/{id}/opt-out/ (and `last_contact_at`, which is null until mail exists). The `status` filter and field already read `opted_out_at`.
8. seed_demo guard: dev settings module + DEBUG on + connected database equals DEV_DATABASE_NAME (new setting, the name from DATABASE_URL). Under the test settings it refuses, so the seeder class is tested directly on nudge_test and the command is tested only for refusing.
9. The demo Owner's email is random (demo-xxxxxxxx@example.com) and the password is random; both appear only on the console. The workspace is found by its name ("Nudge Demo Workspace"), companies by name and contacts by email, so a second run adds nothing; after a first run a lost password is replaced with `--reset-password`.
10. seed_demo writes through the real services, so the demo data is validated and audited (8 `company.create` and 25 `contact.create` rows). It creates no teams and no deals yet (no module for them), and no opted-out contacts.
11. Phone numbers in the demo data are made-up Pakistani mobile numbers that pass the real validator.

## 9h. Email through SMTP (9 Nov 2026)

What was built and the choices I made. Tell me to change any of them.
1. Settings come from separate environment variables (the old single EMAIL_URL is gone): EMAIL_BACKEND (default: the console backend), EMAIL_HOST (localhost), EMAIL_PORT (25), EMAIL_USE_TLS (False), EMAIL_HOST_USER, EMAIL_HOST_PASSWORD, DEFAULT_FROM_EMAIL, EMAIL_TIMEOUT (10 seconds). SMTP is used only when EMAIL_BACKEND is `django.core.mail.backends.smtp.EmailBackend`. `.env.example` has the names and no value for the password. Your private `.env` may still hold an old EMAIL_URL line; it is ignored now and can be deleted.
2. Startup checks: a timeout of 0 or less stops the start (dev and prod); production also refuses a backend that delivers nothing (console, in-memory, dummy, file). Messages name the setting, never a value.
3. Test settings always use the in-memory backend, whatever `.env` says; failure tests use a fake backend that raises. No test opens a network connection.
4. The failure log is one ERROR line: error class, SMTP status code (if any), errno (if any), subject. No traceback, no exception text (a server reply can echo a login), no recipient, no body, no settings.
5. Which paths hide a failure, and why (chosen per path in the container):
   | Path | On SMTP failure | Why |
   |---|---|---|
   | POST /auth/register/ | 202, logged | An unknown address sends a code and a known one a notice, but a 503 on some of them would let a prober see which addresses behave differently when the server flaps. |
   | POST /auth/resend/ | 202, logged | Only an existing unverified account sends mail; a 503 there would reveal exactly that. |
   | POST /auth/reset/ | 202, logged | Only an existing active account sends the link; a 503 would reveal the account. |
   | Notice after POST /auth/password/ and /auth/reset/confirm/ | 204, logged | The password is already changed and every session ended; a 503 would tell the client it failed when it did not. |
   | Anything that must be sent and has no secret to protect (send_test_email, a future invitation) | 503 COMMON_SERVICE_UNAVAILABLE, logged | The caller needs to know. Never 500. |
   Today every API path that sends mail is in the first four rows, so no current endpoint answers 503 for a mail failure; the strict sender exists for the command and for what comes next.
6. Cost of hiding failures: when SMTP is down, a new user gets "a code is on its way" and nothing arrives, and the only signal is the ERROR log line. A monitor on `Email delivery failed` is needed before real users. Resend and reset can be repeated by the user (1 per 30 s per address, 3 per hour for reset).
7. Sending is still synchronous, so a dead SMTP server delays each of these requests by up to EMAIL_TIMEOUT seconds. A queue (after the midterm) removes that delay and the timing difference between "sent" and "nothing to send".
8. `send_test_email <address>` (development only, same guard as seed_demo: dev settings, DEBUG on, dev database) sends one message through the strict sender and says only that it worked or that it failed (the reason is in the log). Tests only check that it refuses elsewhere and sends nothing.
9. `NUDGE_ENV_FILE` (new, optional) points the settings at another env file; the tests use it to start a fresh process with no `.env`.

## 9i. Designed HTML emails (10 Nov 2026)

The verification code, the "someone tried to sign up" notice and the password-reset email are now multipart/alternative: a plain-text part (exactly as before) and an HTML part. Tell me to change any of these choices.
1. Design (polished 10 Nov 2026, colours from the app's Nudge-frontend/src/styles/tokens.css): light by default, white page, white card (12px radius, #d9d9d9 border) topped by a 3px green (#3ecf8e) line, then a 40px logo mark (the favicon: #171717 rounded square, white dot, green chevron, drawn as a table cell with text characters, no image) beside the word Nudge. Heading 28px bold, body 16px at line-height 1.6, padding 40px (24px on phones, one column). The code is 40px monospaced with 10px letter spacing in a #f2f2f2 box with a thin border, and a small line below it with the validity. Buttons are black, white text, 14px vertical padding, 8px radius, full width on phones, with the plain link below. Footer: a divider, a line saying the mail was sent automatically and replies are not monitored, and "Nudge © <year>" (the year comes from the injected Clock). Dark mode (`prefers-color-scheme`) is pure black and grey (#000, #ededed, #333, inverted button), no blue. Readability is tested: body text at least 15px, muted text at least 4.5:1 contrast in both modes. Checked once at 360px wide in Edge (no horizontal scroll, button full width). System fonts only.
2. Where things live: `common/email_templates/` (layout.html, verify_code.html, link_action.html, renderer.py). Every sentence is a line in `common/messages.py`; templates only insert values. The renderer uses Django's template engine on its own with autoescape on, so every inserted value (name, code, link) is HTML-escaped.
3. Services still call the `EmailSender` interface. `EmailMessage` gained optional `kind`, `recipient_name`, `code`, `link` and `html_body`. `HtmlEmailSender` (common/infra/email.py) renders the HTML for a message that has a kind and hands it to `DjangoEmailSender`, which passes it to Django's `send_mail(html_message=...)`. The container's strict sender is now `HtmlEmailSender(DjangoEmailSender())`; the quiet sender wraps that. The failure rules of 9h are unchanged.
4. The text part, subject and the code or link are byte-for-byte what they were, so the frontend and the existing tests are unaffected. The renderer never logs; the failure log still holds only error kind, SMTP code, errno and subject.
5. The "password was changed" notice and the test message stay plain text: they were not in the design.
6. Name in the greeting: the user's `full_name` is passed to the template (escaped). The greeting is left out when no name is given.
7. `python manage.py preview_email verify_code|register_existing|reset_link` (development only, same guard as send_test_email) writes the HTML with sample values to a temporary file and prints its path. Nothing is sent. `send_test_email <address> --kind <kind>` sends the same designed email with the same sample data (common/management/email_samples.py, never real user data) through the strict sender; without --kind it still sends the plain test message.
8. Not verified here: how Gmail, Outlook and Apple Mail draw it. Only the markup is tested; look at the preview and at a real send (`send_test_email` does not use the designed layout).

## 10. Deployment-step items (recorded 2 Nov 2026)

- PostgreSQL: production uses the same major version as development (18).
- Roles, created at the deployment step (they are not needed for the midterm):
  - nudge_app: the role the API connects as. Not a superuser. Gets REVOKE UPDATE, DELETE, TRUNCATE ON audit_logs (design doc), so the append-only rule does not rely on the trigger alone.
  - nudge_test_runner: CREATEDB, not a superuser, owns nudge_test.
  - Until then TEST_DATABASE_URL uses postgres; the _test name and localhost checks in common/testdb.py stay mandatory.
- Connection pooling: CONN_MAX_AGE=60 until then; at the production step add psycopg-pool and Django's built-in pool.
