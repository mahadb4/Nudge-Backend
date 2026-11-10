# API contract

Schema authority: nudge_schema_v3_1.sql (50 tables). Codes are from nudge_db_design_v3_1.md.
Phase tag on every endpoint: [midterm] or [later]. Midterm = sign-up, login, profile, database connectivity, CRUD for stages, companies, contacts, deals, audit log, API docs.
Your answers to QUESTIONS.md (2 Nov 2026) are applied. (Q-n) tags show which answer a rule comes from.
docs/ARCHITECTURE.md is the authority for layering, error codes, pagination shapes and rate limiting. Where this file and ARCHITECTURE.md disagree, ARCHITECTURE.md wins.
Q-23: Python 3.13.9. Q-28: rules cross-checked against docs/nudge_validation_spec_v3_1.md; differences are listed in BACKEND_PLAN section 6 and GAP_REPORT section 3.
Length rule (Q-30): where the frontend limit is stricter than the column, the frontend limit is enforced and the column is only the ceiling.

Build order (9 Nov 2026): authentication and authorization first; see BACKEND_PLAN section 3. Postponed until after the midterm, although specified here: cursor pagination and the full query parser, the token bucket and Redis (section 9; a simple fixed-window attempt limit is used instead, still answering 429 COMMON_RATE_LIMITED with Retry-After), GET/DELETE /auth/sessions/, GET /audit-logs/, and all /deals/ endpoints.

## 0. Conventions

Base and paths
- Prefix /api/v1/. Set VITE_API_URL=http://localhost:8000/api/v1, so the paths the frontend already calls (/auth/login/ and so on) work unchanged.
- Trailing slash on every path, as the frontend uses.
- JSON only (except CSV export and import). UTF-8.

Field names
- snake_case on the wire. The client only accepts error keys that match /^[a-z_]{1,40}$/, so camelCase keys would be dropped.
- Where a frontend field maps to exactly one column, the frontend name is used: deal name (deals.title), contact title (contacts.job_title), company_id, contact_id (deals.primary_contact_id), lost_reason, owner_id.
- Where the frontend field is display text (close, created, last, sync, when, time), the column name is used instead: expected_close_date, created_at, last_contact_at, last_synced_at, updated_at.
- Contact names are first_name + last_name, plus read-only name (Q-14). The frontend form gets two fields.
- Smallint codes are sent as lowercase strings, mapped from the domain enums of each module. Example: visibility "private" | "team" | "organization" (1, 2, 3).
- Request bodies: Content-Type application/json only, at most 1 MB, unknown fields -> 400 COMMON_VALIDATION_FAILED. Client-computed fields (organization_id, role, version increments, created_at) are never read from the body (ARCHITECTURE 6).

Authentication
- Access token (JWT, 10 minutes, claims user_id, sid, jti) in the Authorization: Bearer header. It is held in memory by the frontend (setAccessToken).
- Refresh token in an httpOnly cookie nudge_refresh, Path=/api/v1/auth/. Only /auth/ endpoints read it.
- Endpoints that read or set the cookie require X-CSRFToken matching the csrftoken cookie.

Organization (Q-22)
- Header X-Organization-ID (uuid) selects the organization. If it is missing and the user has exactly one active membership, that one is used.
- Missing with several memberships: 400 TENANCY_ORGANIZATION_REQUIRED. Unknown, not a member, suspended or removed membership, or deactivated organization: 404 COMMON_NOT_FOUND.

Errors (ARCHITECTURE 4)
- Every error body is {"code": "AUTH_BAD_CREDENTIALS", "detail": "That email and password do not match."}.
  - The code is the NAME of a member of `class Messages(StrEnum)` in common/messages.py, in UPPER_SNAKE (area first: COMMON_, AUTH_, TENANCY_, VALIDATION_, CRM_, ...).
  - The detail is that member's English text, with any {} filled in.
  - The frontend decides behaviour from the code only, never from the text. A text can change freely; renaming a code is a breaking change.
- 400 validation adds the failing fields. The frontend client must read body.fields instead of the top-level keys (frontend change 22):
  {"code": "COMMON_VALIDATION_FAILED", "detail": "...", "fields": {"email": [{"code": "VALIDATION_EMAIL_INVALID", "detail": "..."}]}}
- 409 version conflicts add "current": <resource>. 429 responses add the Retry-After header.
- The full code list is `Messages` in common/messages.py; the auth-flow codes are listed in section 2. Codes named in this file for later modules (CRM_*, ACCOUNTS_*, WORKFLOW_*) are added to `Messages` when that module is built.

Errors that apply to every endpoint unless stated otherwise:
| Status | Code | When |
|---|---|---|
| 400 | COMMON_VALIDATION_FAILED, COMMON_MALFORMED_JSON, COMMON_INVALID_CONTENT_TYPE, COMMON_BODY_TOO_LARGE | Bad body, unknown field, bad query parameter |
| 401 | AUTH_ACCESS_TOKEN_INVALID | No access token, or it is malformed, expired or its session is revoked (not on public endpoints). The client refreshes once and retries |
| 403 | COMMON_FORBIDDEN | Role is not allowed (stated per endpoint) |
| 404 | COMMON_NOT_FOUND | Id does not exist, is soft-deleted, or belongs to another organization or user |
| 429 | COMMON_RATE_LIMITED | Token bucket empty; Retry-After, X-RateLimit-Limit, X-RateLimit-Remaining headers |
| 500 | COMMON_SERVER_ERROR | Unexpected error; no stack trace or internal text |

Lists (ARCHITECTURE 7)
- Query parameters are parsed against a whitelist per resource (filters, sort, q, page or cursor, page_size). Anything else -> 400 COMMON_VALIDATION_FAILED with the parameter named in fields.
- Sort: ?sort=<field> or ?sort=-<field>, one field, from the resource's allowed list.
- q: cleaned, 2-100 characters; an empty q means no search.
- Offset lists (small: companies, contacts, members): ?page=1&page_size=25 (1-100) -> {"count", "next", "previous", "results"}.
- Cursor lists (large: audit log, deals per stage, later inbox): ?cursor=&page_size= -> {"results", "next_cursor"}.
  - The cursor is base64url of (sort value, id). The query uses WHERE (sort, id) < (x, y) LIMIT n + 1; next_cursor is null on the last page.
  - A malformed cursor -> 400 VALIDATION_CURSOR_INVALID.

Concurrency
- deals: body must carry version (deals.version). The update runs WHERE id = ? AND version = ?. 0 rows -> 409 COMMON_VERSION_CONFLICT with "current": <deal>.
- companies and contacts have no version column. The body carries updated_at as read; the update runs WHERE updated_at = ?. 0 rows -> 409 (Q-15).
- Delete is soft (deleted_at). Restore endpoints are later (Q-15).

Visibility (Q-20)
- New companies, contacts and deals default to visibility "organization" unless the request says otherwise.
- Manager is treated as Member.

Money and time
- amount: decimal string with 2 places, e.g. "18000.00". currency: ISO 4217. Totals are always lists per currency, [{"currency", "amount", "count"}], and are never added across currencies.
- Timestamps are ISO 8601 UTC. expected_close_date is YYYY-MM-DD. Time zones are IANA names.

Audit
- Every write below appends one audit_logs row: action 'object.verb', object_type, object_id, details {"label": <readable name at the time>, "changes": {...}}, ip_address. Listed per endpoint as "audit:".

## 1. common

### GET /health/ [midterm]
Public. Runs SELECT 1 and checks that the users table can be read.
200 {"status": "ok", "database": "ok"}. 503 {"code": "COMMON_SERVICE_UNAVAILABLE", "detail": "..."}.
Tables: none (users, read-only probe).

### GET /schema/ and GET /docs/ [midterm]
OpenAPI 3 from drf-spectacular, and Swagger UI. Public when DEBUG is True; in production only for users with is_staff (Q-21).

## 2. accounts: auth

Auth-flow codes (texts are in common/messages.py):
| Code | Status | Used by |
|---|---|---|
| AUTH_CODE_SENT | 202 | register, resend (same body for known and unknown emails, also when the mail server fails or times out) |
| AUTH_RESET_LINK_SENT | 202 | reset (same body for known and unknown emails, also when the mail server fails or times out) |
| AUTH_BAD_CREDENTIALS | 401 | login |
| AUTH_EMAIL_UNVERIFIED | 403 | login |
| AUTH_INVALID_CODE | 400 | verify |
| AUTH_CODE_ATTEMPTS_EXCEEDED | 429 | verify |
| AUTH_INVALID_TOKEN | 400 | reset confirm |
| AUTH_WRONG_CURRENT_PASSWORD | 400 (in fields.current) | password change |
| AUTH_ACCESS_TOKEN_INVALID | 401 | every Bearer endpoint |
| AUTH_SESSION_INVALID | 401 | refresh (missing, expired, revoked or reused cookie; one code so reuse is not revealed) |
| AUTH_CSRF_FAILED | 403 | every cookie or CSRF-checked endpoint |
| COMMON_RATE_LIMITED | 429 | every bucket in section 9 |

### GET /auth/csrf/ [midterm] (built, A4)
Public. Sets the csrftoken cookie. 200 {"csrf_token": "..."}. Tables: none.

### Email delivery failures (all paths that send mail)
If the mail server fails or times out (10 seconds by default, EMAIL_TIMEOUT), the endpoint answers exactly as if the mail had gone out and a failure line is logged (error kind, SMTP status code and subject; never the address, the body, the login or the password). Paths: POST /auth/register/, /auth/resend/ and /auth/reset/ (202: a different answer would reveal whether an address has an account) and the "password was changed" notice of POST /auth/password/ and /auth/reset/confirm/ (the change is already saved, so the answer stays 204). (Visible change, 10 Nov 2026: the verification code, the "someone tried to sign up" notice and the reset email are now sent as an HTML email with the same plain-text version as before. Subjects, codes, links and every response are unchanged.) A user whose code or link never arrives asks again with /auth/resend/ or /auth/reset/. Code that needs the mail to be sent (a future invitation) uses the strict sender and answers 503 COMMON_SERVICE_UNAVAILABLE, never 500.

### POST /auth/register/ [midterm] (built, A4)
Public, CSRF required.
Request (same shape as the frontend sign-up form, src/pages/Auth.tsx, src/api/auth.ts, except type):
- business: {"name", "company", "email", "password", "type": "business", "timezone"}
- individual: {"name", "email", "password", "type": "individual", "timezone"}. The form sends company as undefined, so JSON.stringify drops the key.
- type is lowercase on the wire, like every other code. The frontend currently sends "Individual" / "Business" and must map them (frontend change 26). "Individual" or "Business" with capitals -> 400 VALIDATION_CHOICE_INVALID. GET /auth/me/ returns "individual" or "business" in "type".
- timezone: the frontend shows the browser zone but does not send it yet (frontend change 5). Until then a missing timezone is a 400, never a server default.
Response: 202 {"code": "AUTH_CODE_SENT", "detail": "..."} for every address. An existing address never gets new rows:
- never verified, and its code expired (more than 10 minutes): the latest sign-up wins. Password, name, timezone and the organization (name, type, timezone) are replaced in one transaction, the earlier code stops working and a new code is emailed (audit: user.register_replace).
- verified, or never verified but its code is still live: nothing changes and nothing is invalidated; that person is sent a "someone tried to register" email (audit: user.register_existing).
Writes, in one transaction:
- users: email (lowercased), password (Argon2 hash), full_name, timezone, is_active true.
- organizations:
  - account_type 1 Individual or 2 Business, from type;
  - name = the cleaned company (Business) or the user's own cleaned full_name (Individual, spec: organizations.name);
  - timezone = the user's timezone.
- memberships: role 1 Owner, status 1.
- deal_stages: 7 defaults (as nudge_create_default_stages).
- audit: user.register.
Then a 6-digit code is created and sent (Q-1). The cache keeps only an HMAC of it, for 10 minutes, with 5 tries. No table.
Rules:
- name: 2-80, a letter, no < >.
- type: "individual" or "business"; anything else (including capitalised values) -> VALIDATION_CHOICE_INVALID.
- company:
  - business: required, 2-120, no < > (VALIDATION_REQUIRED, VALIDATION_TOO_SHORT, VALIDATION_TOO_LONG, VALIDATION_MARKUP_NOT_ALLOWED).
  - individual: must be absent, null or empty; a non-empty value -> VALIDATION_COMPANY_NOT_ALLOWED.
- email: rules in BACKEND_PLAN section 6.
- password: 8-128 (Q-2) plus the rules in BACKEND_PLAN section 6.
- timezone: a valid IANA name.
Errors: 400 fields; 429.

### POST /auth/verify/ [midterm] (built, A4)
Public, CSRF required. Request: {"email", "code"} (exactly 6 digits).
200 {"access", "user": <Me>}. Sets nudge_refresh as a session cookie (no Max-Age); the session lasts 1 day.
- The user in the reply is the one just verified (`verified` is true); `organization` is the oldest active membership.
- Unknown fields -> 400 VALIDATION_UNKNOWN_FIELD; a malformed email or code -> 400 with `fields`.
Writes, in one transaction: users.email_verified_at, user_sessions (one row, the refresh value stored only as sha256), audit user.email_verify.
Errors:
- 400 AUTH_INVALID_CODE for a wrong, used, expired or unknown code or an unknown email: same status and body every time.
- 429 AUTH_CODE_ATTEMPTS_EXCEEDED once 5 wrong codes were tried for that email (also for an unknown email); Retry-After 30; a new code lifts it.
- 429 COMMON_RATE_LIMITED: more than 20 attempts per minute from one IP.
- 403 AUTH_CSRF_FAILED.

### POST /auth/resend/ [midterm] (built, A4)
Public, CSRF required. Request: {"email"}. 202 {"code": "AUTH_CODE_SENT", "detail": "..."} for every address.
A code is sent only to an existing, unverified account; the previous code stops working and the try counter resets. Nothing is sent to unknown or verified addresses.
Errors: 429 COMMON_RATE_LIMITED (1 per 30 s per email, counted for every address; 20 per minute per IP); 400 with `fields` for a bad email; 403 AUTH_CSRF_FAILED.

### POST /auth/login/ [midterm] (built, A5)
Public, CSRF required. Request: {"email", "password", "remember": bool}. remember is optional (missing or null = false); anything but true/false -> 400 fields.remember. The password is only checked for presence and 128 characters (old passwords still work).
200 {"access", "user": <Me>}. The access token lives 10 minutes (Q-9).
Sets nudge_refresh (Q-9):
- remember true: Max-Age 30 days, and user_sessions.expires_at = now + 30 days.
- remember false: a browser-session cookie (no Max-Age), and expires_at = now + 1 day.
Writes:
- user_sessions: refresh_token_hash = sha256 hex, device_name from User-Agent, ip_address, expires_at.
- users.last_login.
- audit: user.login (actor the user), or user.login_failed (actor_type 2, details {"email_hmac"}: a keyed hash, never the address or the password).
Errors:
- 400 fields.
- 401 AUTH_BAD_CREDENTIALS: same body for an unknown email, a wrong password or an inactive user.
- 403 AUTH_EMAIL_UNVERIFIED (Q-8). Returned only after the password is checked, so it does not reveal which emails exist. No session is created; the frontend sends the user to /verify and calls /auth/resend/.
- 429 COMMON_RATE_LIMITED: 5 attempts per minute per email (right or wrong) and 20 per minute per IP; Retry-After set; 503 when the cache is down (fails closed).

### POST /auth/refresh/ [midterm] (built, A5)
Cookie + CSRF. No body. 200 {"access", "user": <Me>}. Rotates nudge_refresh.
Writes: user_sessions.refresh_token_hash (replaced), last_used_at.
Errors:
- 401 AUTH_SESSION_INVALID when the cookie is missing, expired or revoked.
- 401 AUTH_SESSION_INVALID on reuse of an old refresh token (same code); the session is also revoked (revoked_at).
- 403 AUTH_CSRF_FAILED when the CSRF check fails.
- Every 401 here also clears the cookie (Max-Age 0).
- The session never gets longer: expires_at stays what login set. A 'keep me signed in' cookie gets Max-Age = the time the session has left.
- Two requests with the same cookie at once: one wins, the other ends the session (the frontend must send one refresh at a time).
- Audit: session.reuse_detected (actor the user, object the session).

### POST /auth/logout/ [midterm] (built, A5)
Cookie + CSRF. 204 always; clears the cookie. Only the session's current cookie value ends it; a missing, malformed or old value does nothing (still 204).
Writes: user_sessions.revoked_at; audit user.logout. The access token of that session stops working at once.

### GET /auth/me/ [midterm] (built, A5)
Bearer. The current organization is the oldest active membership until X-Organization-ID is added (A7).
<Me> = {
  "id", "name" (users.full_name), "email",
  "type" ("individual" | "business", from the current organization's account_type),
  "verified" (email_verified_at is not null),
  "phone", "timezone", "quiet_hours_start", "quiet_hours_end" ("HH:MM" or null),
  "organization": {"id", "name", "type", "timezone"}, "role" ("owner" | "admin" | "manager" | "member"),
  "organizations": [{"id", "name", "role"}]
}
Tables: users, memberships, organizations.
Errors: 401 (the frontend treats this as signed out).

### PATCH /auth/me/ [midterm] (built, A7)
Bearer. Only the fields that are sent change; an empty body changes nothing. null clears phone and both quiet-hours times. Audit details hold the field names only.
Quiet hours: after the change both are set or both are empty (VALIDATION_QUIET_HOURS_PAIR on the empty one). Times are "HH:MM" (VALIDATION_TIME_INVALID). Phone: "+" and a valid number, stored as E.164 (VALIDATION_PHONE_NEEDS_PLUS, VALIDATION_PHONE_INVALID). Unknown fields, including email, role and id -> 400 VALIDATION_UNKNOWN_FIELD.
GET /auth/me/ now honours X-Organization-ID for "organization" and "role" (unknown or foreign id -> 404) and returns quiet_hours_start and quiet_hours_end.
Request (all optional): {"name", "phone", "timezone", "quiet_hours_start", "quiet_hours_end"}.
200 <Me>. audit: user.profile_update.
Writes users.full_name, users.phone, users.timezone, users.quiet_hours_start, users.quiet_hours_end.
Rules:
- name: 2-80 after clean, a letter, no < > (Q-30).
- phone: international format with '+' and the country code, normalised to E.164 with phonenumbers; a number without '+' -> 400 (Q-12).
- timezone: a valid IANA name (zoneinfo).
- quiet hours: both set or both null.
Email cannot be changed here.
Errors: 400.

### POST /auth/password/ [midterm] (built, A6)
Bearer. Request: {"current", "password"}. 204.
Writes users.password (only if it is still the hash that was checked); revokes all other user_sessions of the user (this device stays signed in); audit user.password_change; the owner gets a "password was changed" email. The new password follows the sign-up rules, and may not equal the current one (VALIDATION_PASSWORD_SAME_AS_CURRENT).
Errors: 400 COMMON_VALIDATION_FAILED with fields.current = AUTH_WRONG_CURRENT_PASSWORD; with fields.password for the rules; 429 (bucket password_change_user).

### POST /auth/reset/ [midterm] (built, A6)
Public, CSRF required. Request: {"email"}. 202 {"code": "AUTH_RESET_LINK_SENT", "detail": "..."} always.
Sends a link to /new-password?token=<token>, valid 1 hour, single use. The token must match /^[\w-]{4,200}$/.
The token is '<user id hex>-<expiry>-<hmac>' (no email in it). Only an existing, active account gets a link; an unknown address gets the same 202 and nothing else (no email, no audit).
Tables: users (read). audit: user.password_reset_request (only when the user exists).
Errors: 429 (3 per hour per email, 10 per hour per IP).

### POST /auth/reset/confirm/ [midterm] (built, A6)
Public, CSRF required. Request: {"token", "password"}. 204.
Writes users.password (only if the hash the link was made for is still there); revokes all user_sessions; audit user.password_reset; the owner gets a "password was changed" email.
A link stops working when it is used, when the user signs in, when the password changes any other way, and after 1 hour. A reset does not verify an unverified email.
Errors: 400 AUTH_INVALID_TOKEN (wrong shape, wrong, used or expired: same body, no fields); 400 COMMON_VALIDATION_FAILED with fields.password (the link stays usable); 429 (10 per hour per IP).

### GET /auth/sessions/ [midterm]
200 [{"id", "device_name", "ip_address", "created_at", "last_used_at", "current": bool}].
Reads user_sessions of the caller WHERE revoked_at IS NULL AND expires_at > now(). Not paginated (one row per device).

### DELETE /auth/sessions/{id}/ [midterm]
204. Sets user_sessions.revoked_at. audit: session.revoke. 404 if the session is not the caller's.

### POST /auth/oauth/{google|microsoft}/start/ and GET /auth/oauth/{provider}/callback/ [later] (Q-3)
Not built for the midterm. The frontend hides the Google, Microsoft and SSO buttons in real mode. No table holds a provider subject id (G-A5), so the approach is decided later.

### Demo access (Q-4)
There is no demo endpoint and no bypass. `python manage.py seed_demo [--reset-password]` (built; refuses unless the settings are config.settings.dev, DEBUG is on and the connected database is the development database) creates:
- a demo organization "Nudge Demo Workspace" with the 7 default stages, 8 companies and 25 contacts (companies and deals from the frontend's seed.ts come later: deals do not exist yet);
- a verified Owner with a random email (demo-xxxxxxxx@example.com) and a random password, both printed once. Running it again duplicates nothing and prints the owner's email only; --reset-password prints a new password.
That user signs in through POST /auth/login/ like anyone else.

## 3. accounts: organizations, members, teams, invitations

### GET /organizations/ [midterm]
200 [{"id", "name", "type", "role"}]. The workspace switcher.
Reads memberships (status 1) JOIN organizations (deactivated_at IS NULL).

### GET /organizations/current/ [midterm] (built, A7)
Header X-Organization-ID is required when the user has several organizations (400 TENANCY_ORGANIZATION_REQUIRED); an organization the user does not belong to is 404.
200 {"id", "name", "type", "timezone", "automation_paused": bool}.
Reads organizations (automation_paused_at, deactivated_at).

### PATCH /organizations/current/ [midterm] (built, A7)
Only the sent fields change (unknown fields such as currency or automation_paused -> 400). audit details: field names.
Owner or Admin. Request: {"name"? (2-120, no < >), "timezone"? (IANA)}. 200 as GET.
Writes organizations.name, organizations.timezone. audit: organization.update.
No currency field: the 'Default currency' select is removed from Workspace settings (Q-11). Errors: 400, 403.

### GET /members/ [midterm] (read-only; feeds owner selects and filters)
?status=active|suspended|removed (default active), ?q=.
200 page of {"id" (membership id), "user_id", "name", "email", "role", "status", "teams": [{"id", "name", "is_lead"}], "last_active_at"}.
Reads memberships, users, team_members, teams, user_sessions (max last_used_at). One query with prefetch.

### PATCH /members/{id}/ [later]
Owner or Admin. Request: {"role"?, "status"?}.
Writes memberships.role, memberships.status. audit: membership.role_change / membership.status_change.
Errors: 409 ACCOUNTS_LAST_OWNER when the change would leave no active Owner. Only an Owner may grant Owner.

### DELETE /members/{id}/ [later]
Sets memberships.status = 3 (rows are never deleted). Same 409.

### GET/POST /invitations/, POST /invitations/{id}/resend/, DELETE /invitations/{id}/ [later]
Request: {"email", "role", "team_id"?}.
Writes invitations: token_hash, expires_at = now + 7 days. Re-inviting the same email updates the pending row.
Errors: 409 ACCOUNTS_ALREADY_MEMBER when the email is already a member.

### POST /invitations/accept/ [later]
Public + token. Creates memberships, sets invitations.accepted_at.

### GET /teams/ [midterm] (read-only)
The spec marks teams and team_members as Midterm tables because visibility = team depends on them.
200 [{"id", "name", "members": [{"membership_id", "name", "is_lead"}]}], ordered by lower(name). Not paginated (one organization's teams).
Reads teams, team_members, memberships, users; two queries (teams + prefetch).
Members also see their own teams in GET /members/.
Midterm effect: the API cannot create teams, so visibility "team" only works with teams made by seed_demo (Sales, Support from the frontend seed).

### POST /teams/, PATCH/DELETE /teams/{id}/, POST/DELETE /teams/{id}/members/ [later]
Owner or Admin. Business organizations only (spec: 'departments inside a business organization').
Rules: name 1-80 after clean, unique per organization ignoring case (409 ACCOUNTS_TEAM_NAME_TAKEN); only Owner or Admin set is_lead.
Writes teams, team_members.
Errors: 409 ACCOUNTS_TEAM_IN_USE when deleting a team that still has Team-visible records (FK RESTRICT).

## 4. crm (midterm)

Visibility rule on every crm list and detail: Owner and Admin see all live rows. Others see visibility = organization, OR owner_id = me, OR (visibility = team AND team_id IN my teams).
Soft-deleted rows (deleted_at not null) behave as 404 (Q-15 covers restore).

### Deal stages

GET /deal-stages/ [midterm] (built, A7; all five deal-stage endpoints)
Any active member. All stage endpoints need the Bearer token and follow the X-Organization-ID rule above. A stage id of another organization is 404 COMMON_NOT_FOUND. Every write locks the organization's stage rows, runs in one transaction and writes an audit row (details: names, never secrets).
200 [{"id", "name", "position", "outcome": "open" | "won" | "lost", "deal_count"}] ordered by position. Not paginated (at most 12).
Reads deal_stages, deals (count of live deals).

POST /deal-stages/ [midterm]
Owner or Admin. Request: {"name"}. Inserted as an open stage before the won stage. 201.
Rules (Q-5): name 1-40 after clean, no < >, unique per organization ignoring case (uq_deal_stages_1); at most 12 stages in total.
Writes deal_stages. audit: deal_stage.create.
Errors: 400 (including CRM_STAGE_LIMIT_REACHED), 403, 409 CRM_STAGE_NAME_TAKEN. The 201 body is the new stage with deal_count 0; positions of Won and Lost move up by one.

PATCH /deal-stages/{id}/ [midterm]
Owner or Admin. Request: {"name"}. Writes deal_stages.name. audit: deal_stage.update.
Won and Lost stages cannot be renamed (Q-5): 400. Errors: 400, 403, 409 duplicate.

PUT /deal-stages/order/ [midterm]
Owner or Admin. Request: {"ids": [all stage ids in the new order]}. 200 list.
Rules (Q-5): the list must contain every stage exactly once; the first open stage stays first; open stages, then the one won stage, then the one lost stage last.
Positions are rewritten 0..n-1 in one transaction, unique and gap-free (spec). An order that is already current changes and audits nothing. A wrong list -> 400 fields.ids = CRM_STAGE_ORDER_INVALID; a missing or non-list ids -> VALIDATION_REQUIRED / VALIDATION_LIST_INVALID.
Writes deal_stages.position. audit: deal_stage.reorder. Errors: 400, 403.

DELETE /deal-stages/{id}/ [midterm]
Owner or Admin. 204. Only open stages; Won and Lost cannot be deleted (Q-5): 400 CRM_STAGE_FIXED. The remaining positions are closed up to 0..n-1.
Errors: 409 CRM_STAGE_IN_USE when any deal uses it (soft-deleted deals count, because the foreign key still blocks the delete); 409 CRM_LAST_OPEN_STAGE when it is the last open stage.

### Companies (built, 9 Nov 2026)

All company endpoints: Bearer token; X-Organization-ID rule as for stages; any active member; the visibility rule above decides which rows exist for the caller (others are 404). Unknown query parameters or body fields -> 400 naming them. Every write is audited and runs in one transaction.

GET /companies/ [midterm]
?q= (name, domain, industry; 2-100 characters; case-insensitive contains), ?owner_id=, ?ordering=name|-created_at (default name), ?page=, ?page_size= (1-100, default 25).
Response {"count", "next", "previous", "results": [<Company>]}; next/previous are absolute URLs or null. Always five queries.
Errors: 400 with the parameter named (VALIDATION_PAGE_INVALID, VALIDATION_PAGE_SIZE_INVALID, VALIDATION_CHOICE_INVALID, VALIDATION_TOO_SHORT/LONG, VALIDATION_UUID_INVALID, VALIDATION_UNKNOWN_FIELD).
<Company> = {
  "id", "name", "domain", "industry",
  "size_range": "1-10" | "11-50" | "51-200" | "201-500" | "500+" | null,
  "owner": {"id", "name"}, "visibility", "team_id",
  "people_count", "open_deal_count", "open_value": [{"currency", "amount"}],
  "created_at", "updated_at"
}
Reads companies (index ix_companies_2 for the name order), users (owner, select_related), contacts (count subquery), deals + deal_stages (one grouped query for the page: open count and sum per currency).

POST /companies/ [midterm]
Request: {"name", "domain"?, "industry"?, "size_range"?, "owner_id"? (default me), "visibility"? (default organization, Q-20), "team_id"?}. 201 <Company>.
Rules:
- name: 2-120, no < > (Q-30). Unique per organization ignoring case among live rows; a service check, since the DB has only an index (Q-16).
- domain: lowercase host name, <= 253, unique among live rows (uq_companies_1) (Q-16). A URL ('https://www.acme.com/path') is refused with VALIDATION_DOMAIN_INVALID. The spec would keep only the host; we keep our rule (BACKEND_PLAN section 6).
- visibility team: team_id must be a team of the organization that the caller belongs to (spec).
- industry: <= 80.
- owner: an active member.
- team_id: required if and only if visibility = team (ck_companies_visibility_team_id).
Writes companies. audit: company.create.
A domain is lowercased; a URL, a path or a name without a dot is VALIDATION_DOMAIN_INVALID; null or blank clears it. industry: null or blank clears it. size_range: "1-10" | "11-50" | "51-200" | "201-500" | "500+" or null. visibility: "private" | "team" | "organization". Rules for the links: VALIDATION_MEMBER_INVALID (owner_id), VALIDATION_TEAM_REQUIRED / VALIDATION_TEAM_NOT_ALLOWED / VALIDATION_TEAM_INVALID (team_id).
Errors: 400; 409 CRM_COMPANY_NAME_TAKEN or CRM_COMPANY_DOMAIN_TAKEN.

GET /companies/{id}/ [midterm]
200 <Company>. People and deals come from /contacts/?company_id= and /deals/?company_id=.

PATCH /companies/{id}/ [midterm]
Request: any POST field + "updated_at" (required, exactly as read, ISO 8601 with offset). Only the sent fields change; null clears domain, industry, size_range. 200 <Company>. audit: company.update (label and changes {field: {from, to}}).
Errors: 400; 404; 409 CRM_COMPANY_NAME_TAKEN / CRM_COMPANY_DOMAIN_TAKEN; 409 COMMON_VERSION_CONFLICT with "current": <Company> when updated_at is stale.

DELETE /companies/{id}/ [midterm]
204. Sets companies.deleted_at. audit: company.delete.

### Contacts (built, 9 Nov 2026; opt-out and opt-in are not built yet)

Same rules as companies: Bearer token, X-Organization-ID rule, any active member, the visibility rule decides which rows exist for the caller (others are 404), unknown query parameters or body fields are 400 and named, every write is audited in one transaction. PATCH needs `updated_at` exactly as read (409 COMMON_VERSION_CONFLICT with `current`).

GET /contacts/ [midterm]
Filters: ?q= (first_name, last_name, email, company name; 2-100 characters; case-insensitive contains), ?status=active|opted_out, ?owner_id=, ?company_id=, ?ordering=name|-created_at (default name = last name, then first name; contacts without a last name sort last), ?page=, ?page_size= (1-100, default 25). Response {"count", "next", "previous", "results": [<Contact>]}. Four queries however many rows (count, page, owner names, company names).
<Contact> = {
  "id", "first_name", "last_name", "name" (read-only), "email", "phone", "title" (job_title),
  "company": {"id", "name"} | null, "owner": {"id", "name"}, "visibility", "team_id",
  "status": "active" | "opted_out" (from opted_out_at), "opted_out_at",
  "source": "manual" | "csv" | "web_form" | "email",
  "last_contact_at" (null until mail exists),
  "created_at", "updated_at"
}
The frontend 'Suspended' status and 'location' have no column (G-A3).
Reads contacts (ix_contacts_2 for the name order), companies, users. The company is shown only if the caller can see that company (otherwise null).

POST /contacts/ [midterm]
Request: {"first_name", "last_name"?, "email", "phone"?, "title"?, "company_id"?, "owner_id"?, "visibility"? (default organization, Q-20), "team_id"?}. 201 <Contact>. source = 1 Manual.
Rules:
- first_name: 1-80 after clean, a letter, no < >. last_name: 0-80, no < >, and a letter if not empty (spec person-name rule) (Q-14).
- Duplicate email: 409 CRM_CONTACT_EMAIL_TAKEN. The body adds "existing": {"id", "name"} only when the caller can see that contact (spec: show the existing contact). Otherwise only the code, so a private contact is not revealed.
- email: required for manual creation (Q-14). Rules in BACKEND_PLAN section 6; unique among live rows (uq_contacts_1).
- phone: optional; '+' and the country code required, stored as E.164 (Q-12).
- title: <= 80 (Q-30).
- company_id: in the same organization and visible to the caller.
Writes contacts. audit: contact.create.
company_id: a live company of this organization that the caller can see (VALIDATION_COMPANY_INVALID). owner_id and team_id follow the company rules (VALIDATION_MEMBER_INVALID, VALIDATION_TEAM_*).
Errors: 400; 409 CRM_CONTACT_EMAIL_TAKEN.

GET /contacts/{id}/ [midterm]
200 <Contact>. The detail screen also calls /deals/?contact_id= (later: /threads/?contact_id=).

PATCH /contacts/{id}/ [midterm]
Any POST field + "updated_at" (required). Only the sent fields change; null clears last_name, phone, title, company_id. 200 <Contact>. audit: contact.update (label and {field: "changed"} for personal fields, {from, to} for owner, company, visibility, team). Email cannot be cleared (every contact is manual for now). Errors: 400, 404, 409 CRM_CONTACT_EMAIL_TAKEN (with "existing" when visible), 409 COMMON_VERSION_CONFLICT with "current".

DELETE /contacts/{id}/ [midterm]
204. Sets contacts.deleted_at. audit: contact.delete.

POST /contacts/{id}/opt-out/ [midterm]
200 <Contact>. Sets opted_out_at = now() if null (idempotent). audit: contact.opt_out.

DELETE /contacts/{id}/opt-out/ [midterm]
Owner or Admin only (Q-17); others get 403. 200. Clears opted_out_at. audit: contact.opt_in, with the previous opted_out_at in details.

POST /contacts/import/ [later]
multipart file. Rules in BACKEND_PLAN section 6. A phone without '+' makes the row invalid (Q-12). Runs as a background job; source = 2.
200 {"imported", "skipped": [{"row", "reason"}]}. audit: contact.import.

GET /contacts/export/ [later]
CSV, formula-safe. audit: contact.export.

### Deals

GET /deals/ [midterm]
Filters: ?stage_id=, ?status=open|won|lost (via deal_stages.outcome), ?owner_id=, ?currency=, ?company_id=, ?contact_id=.
Cursor pagination ordered by (stage position, id) for the board, or -created_at for tables.
200 <Deal> = {
  "id", "name", "company": {"id", "name"} | null, "contact": {"id", "name"} | null,
  "stage": {"id", "name", "outcome"}, "owner": {"id", "name"},
  "amount", "currency", "expected_close_date", "closed_at", "lost_reason",
  "visibility", "team_id", "version", "created_at", "updated_at",
  "waiting": false (until reply drafts exist)
}
Reads deals (ix_deals_1 (organization_id, stage_id, id) serves the first cards of each stage), deal_stages, companies, contacts, users, all select_related.

GET /deals/summary/ [midterm]
?owner_id=, ?currency=.
200 {"stages": [{"stage_id", "count", "totals": [{"currency", "amount"}]}], "open": [{"currency", "count", "amount"}], "won": [...], "lost": [...]}.
Board headers, Home and Reports. One GROUP BY (stage_id, currency) query.

POST /deals/ [midterm]
Request: {"name", "amount", "currency", "stage_id"? (default first open stage), "company_id"?, "contact_id"?, "owner_id"? (default me), "expected_close_date"?, "visibility"? (default organization, Q-20), "team_id"?}. 201 <Deal> with version 1.
Rules:
- name: 2-80, no < > (Q-30).
- amount: required, > 0, at most 2 decimals, < 1,000,000,000,000 (Q-18).
- currency: required, an active ISO 4217 code from the fixed server list (Q-11).
- expected_close_date: optional; a real date <= 2100-12-31, not in the past on create.
- company, contact, stage and owner: in the same organization. The contact does not have to belong to the chosen company (Q-18).
- A stage with outcome won/lost on create sets closed_at; lost requires lost_reason.
Writes deals. audit: deal.create.
Errors: 400.

GET /deals/{id}/ [midterm]
200 <Deal>.

PATCH /deals/{id}/ [midterm]
Request: {"version", "name"?, "amount"?, "expected_close_date"? (past allowed), "company_id"?, "contact_id"?, "owner_id"?, "visibility"?, "team_id"?}. Currency cannot be changed (frontend rule).
200 <Deal> with version + 1.
Writes deals. audit: deal.update with the changed fields.
Errors: 400; 409 COMMON_VERSION_CONFLICT with "current": <Deal>.

POST /deals/{id}/move/ [midterm]
Request: {"version", "stage_id", "lost_reason"?}. 200 <Deal>.
lost_reason: required when the target outcome is lost; free text 1-200 after clean. The UI offers the five frontend reasons as choices (Q-18).
Effects:
- Into won/lost: sets closed_at.
- Back to open: clears closed_at and lost_reason.
- Out of lost: clears lost_reason.
Writes deals.stage_id, closed_at, lost_reason, version. audit: deal.stage_change {"from", "to"}.
Errors: 400, 409 version_conflict.

DELETE /deals/{id}/ [midterm]
Request: ?version=. 204. Sets deals.deleted_at. audit: deal.delete. Errors: 409.

POST /deals/{id}/notes/ [later]
The frontend 'Notes' box has no deals column. It maps to activities type 1 Note (FYP-II table) (G-A4).

GET /deals/{id}/activity/ [later]
Reads activities, email_threads, email_messages.

## 5. audit

### GET /audit-logs/ [midterm]
Owner and Admin only (Q-19); Member and Manager get 403. Filters: ?actor_type=user|system|ai (the frontend 'People' = user, 'Nudge' = system or ai), ?action=, ?object_type=, ?object_id=, ?from=, ?to=. Cursor pagination, newest first.
200 [{"id", "created_at", "actor": {"id", "name"} | null, "actor_type", "action", "action_label", "object_type", "object_id", "object_label"}].
- action_label is a fixed English text for each action code (the frontend shows 'Moved deal to Proposal').
- object_label comes from details.label.
Reads audit_logs (ix_audit_logs_1/2/3) and users. Never UPDATE or DELETE.

### GET /audit-logs/export/ [later]
CSV with the same filters, formula-safe, at most 10,000 rows. audit: audit_log.export.

## 6. mail [later]

| Endpoint | Purpose | Tables |
|---|---|---|
| GET /mailboxes/ | {"id", "email", "provider": "gmail" \| "imap" \| "outlook", "status": "active" \| "error" \| "disconnected", "is_shared", "owner", "last_synced_at", "last_error"} | email_accounts, users |
| POST /mailboxes/connect/{provider}/ -> provider redirect; GET /mailboxes/callback/{provider}/ | Connect | email_accounts.credentials_encrypted, status, sync_cursor |
| POST /mailboxes/{id}/reconnect/ | Sign in again | same |
| DELETE /mailboxes/{id}/ | Sets status 3 and credentials to null (row kept) | email_accounts |
| GET /threads/?status=&mailbox_id=&contact_id=&deal_id= (cursor, last_message_at desc) | Inbox list: subject, contact, deal, last_message_at, status, latest inbound type and confidence | email_threads (ix_email_threads_2), contacts, companies, predictions, prediction_labels, labels |
| GET /threads/{id}/ | Messages: from_name, from_email, sent_at, direction, body_text | email_messages (ix_email_messages_2), message_recipients |
| POST /compose/ | New email for approval | No home today: reply_drafts.message_id is NOT NULL (G-A6) |

Errors: 400, 404, 409 WORKFLOW_RECIPIENT_OPTED_OUT on compose to an opted-out contact.

## 7. ai and workflow [later]

| Endpoint | Purpose | Tables |
|---|---|---|
| GET /reviews/ (cursor) | Pending drafts with the email, contact, deal, type, confidence (0-100 = decision_score x 100), evidence, extracted facts, draft | reply_drafts (status 1), email_messages, predictions (is_final), prediction_labels, labels, extractions, contacts, companies, deals |
| GET /reviews/{id}/ | One item | same |
| PATCH /reviews/{id}/ {"body"} | Edit draft (1-5000) | reply_drafts.body (original_body unchanged) |
| POST /reviews/{id}/type/ {"label"} | Change reply type | corrections (old_label_id, new_label_id), predictions.status 4 |
| POST /reviews/{id}/approve/ {"body", "actions": [ids]} | Approve and queue | reply_drafts.status 2, approved_by_id, approved_at, send_after; deals (version check); follow_ups; contacts. 409 opted_out; 409 version_conflict; 409 when not status 1 |
| POST /reviews/{id}/undo/ | Undo before send; the window is 10 minutes (Q-24) | reply_drafts.status 5 while now < send_after |
| POST /reviews/{id}/reject/ {"reason", "note"} | Reject | reply_drafts.status 5; reason and note have no column (G-A7) |
| POST /reviews/{id}/skip/ | Skip | no column (G-A7) |
| GET/POST /facts/, PATCH/DELETE /facts/{id}/ | Approved facts: key = title, value = body, on = is_active, by = updated_by, updated_at; kind defaults to 4 Other (Q-6) | company_facts |
| GET/POST /templates/, PATCH/DELETE /templates/{id}/ | name, type -> intent_label_id, body, subject, uses (count of reply_drafts.template_id) | email_templates, labels, reply_drafts |
| GET/PUT /automation/ | Per reply type: mode never/approve/auto, min_score, caps. Global mode is derived: 'auto' when any category is in mode 3. The bar is the min_score the API keeps equal on every category (Q-6) | category_settings, labels, organizations.automation_paused_at |
| GET /follow-ups/?status= | List | follow_ups, email_threads, contacts, deals |
| POST /follow-ups/{id}/approve/ {"body"} | Queue a follow-up email | No draft home (G-A6) |
| POST /follow-ups/{id}/snooze/ {"until"} | Snooze | follow_ups.status 2, due_at |
| POST /follow-ups/{id}/done/ | Done | follow_ups.status 3, closed_at, close_reason 1 |
| GET /notifications/, POST /notifications/{id}/read/ | Bell | notifications |
| GET/PUT /notification-settings/ | Per event toggles (G-A10) | notification_channels (per channel only) |
| GET /dashboard/ | Home numbers | reply_drafts, predictions, prediction_labels, deals, meetings |
| GET /reports/?days=7\|30\|90 | Reports | predictions (status 3 vs 4), corrections, reply_drafts (body vs original_body), deals |
| GET /meetings/?from=&to=, POST /meetings/{id}/confirm/ | Calendar | meetings (pending table); 'hold' has no status (G-A11) |
| POST /assistant/conversations/, POST /assistant/conversations/{id}/messages/ | Ask Nudge | assistant_conversations, assistant_messages, assistant_citations, email_chunks |

## 8. integrations [later]

| Endpoint | Tables |
|---|---|
| GET /integrations/ | crm_connections (HubSpot), notification_channels (Slack), email_accounts (Google/Microsoft); calendar and webhooks have no table (G-A12) |
| POST /integrations/hubspot/connect/, DELETE /integrations/hubspot/ | crm_connections, crm_stage_mappings |

## 9. Rate limits (token bucket, ARCHITECTURE 8)

Midterm implementation (9 Nov 2026): a fixed-window counter in the shared cache with the same limits as the policies below (capacity = attempts per window). It answers the same 429 COMMON_RATE_LIMITED with Retry-After, fails closed (503 when the cache is down), and sends no X-RateLimit-* headers. The token bucket with the Redis Lua script is postponed. Policies in use: register_ip, verify_ip (also used by resend), resend_email (also counted by register, for every address).

Each policy is a bucket with capacity C (burst) and refill R tokens per second, keyed by IP, user id or the HMAC of the normalised email. Cost is 1 per request.
- Redis with one atomic Lua script per check. The script reads time from Redis TIME, so app servers with skewed clocks cannot disagree. The in-memory store (dev, one process) uses the injected app clock.
- 429 COMMON_RATE_LIMITED with Retry-After = ceil((cost - tokens) / R). X-RateLimit-Limit and X-RateLimit-Remaining on every limited endpoint.
- Policies live in common/constants.py.

Store failure (Redis down or erroring):
- critical policies fail closed: 503 COMMON_SERVICE_UNAVAILABLE;
- other policies fail open: the request goes through without rate-limit headers, and a warning is logged with the policy name (never the key).

| Policy | Key | C | R (per second) | Critical | Source |
|---|---|---|---|---|---|
| login_email | email HMAC | 5 | 5/60 (0.0833) | yes | ARCHITECTURE |
| login_ip | IP | 20 | 20/60 (0.333) | yes | ARCHITECTURE |
| resend_email | email HMAC | 1 | 1/30 (0.0333) | yes | ARCHITECTURE (Q-1) |
| api_user | user id | 120 | 120/60 (2.0) | no | ARCHITECTURE (every authenticated endpoint) |
| verify_ip | IP | 20 | 20/60 (0.333) | yes | proposal, needs your OK |
| register_ip | IP | 10 | 10/3600 (0.00278) | yes | proposal, needs your OK |
| reset_email | email HMAC | 3 | 3/3600 (0.000833) | yes | proposal, needs your OK |
| reset_ip | IP | 10 | 10/3600 (0.00278) | yes | proposal, needs your OK |
| reset_confirm_ip | IP | 10 | 10/3600 (0.00278) | yes | proposal, needs your OK |
| password_change_user | user id | 5 | 5/900 (0.00556) | yes (proposed; it guards current-password guessing) | proposal, needs your OK |

Verify '5 tries per code' is not a bucket. It is a try counter stored with the code: 429 AUTH_CODE_ATTEMPTS_EXCEEDED on the 6th try.
