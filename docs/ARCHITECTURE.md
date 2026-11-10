NUDGE BACKEND ARCHITECTURE v1
Plain text. Decisions to follow in every module. If code contradicts this file, fix the code or ask before changing this file.

1. STYLE
Modular monolith: one Django project, many modules with strict boundaries. Stateless API (any number of copies behind a load balancer). Slow work (email sync, ML, sending) goes to separate worker processes later, same code base.
Midterm modules: common, accounts, crm, audit.
Later modules: mail, ml, workflow, assistant, integrations, scheduling, outreach.
A module may use common. Modules call each other only through a service interface, never through another module's repository or tables directly.

2. LAYERS AND THE ONE RULE
api  ->  services  ->  repositories  ->  database
Nothing calls upward. domain and common are used by every layer.
- api: controllers. Parse and validate the request into a request DTO, call ONE service method, map the result into a response DTO. No business rules. No SQL.
- services: business rules and use cases. Know nothing about HTTP, DRF, cookies or SQL. Raise AppError subclasses, never HTTP responses.
- repositories: all database access. A Protocol (interface) plus one implementation. Return domain entities, never ORM objects or raw rows. Know nothing about HTTP or rules.
- domain: entities (frozen dataclasses), enums, value objects.
- infra (in common): clock, cache, email sender, password hasher, token signer.
DRF is used only as a thin controller shell (APIView) and for field validation. There is no "views" layer with logic.

3. FOLDER STRUCTURE
config/
  settings/ (base.py dev.py test.py prod.py)
  urls.py
  container.py          composition root: the only place that builds objects and wires them
common/
  messages.py           class Messages(StrEnum): every sentence; the member name is the error code (section 4)
  errors.py             AppError and subclasses (NotFound, Conflict, ValidationFailed, Unauthorized, Forbidden, RateLimited)
  responses.py          success envelope, error envelope, exception handler
  constants.py          header names, cookie names, cache key builders, audit action names, limits
  interfaces.py         Protocols: Clock, Cache, EmailSender, AuditWriter, PasswordHasher, TokenSigner
  pagination.py         PageParams, CursorParams, Page[T], cursor encode/decode
  query.py              ListQuery DTO: filters, sort, q, page; whitelist parser
  ratelimit.py          token bucket (section 8)
  validators.py         email, phone (E.164), currency (ISO 4217), timezone, name rules
  text.py               clean(), clean_multi(): NFC, control chars, trim
  security/             argon2 hasher, jwt signer, csrf helpers, hash helpers
  tenancy.py            TenantContext(user_id, organization_id, role)
  base_repository.py    shared helpers: parameterized query runner, row to entity
  permissions.py        role checks used by controllers
  infra/                clock.py now; cache.py and email.py with the auth slice (implementations of the Protocols)
  health/               GET /api/v1/health/ in the same folders as a module (below)
  management/           the migrate guard (refuses migrate, makemigrations, flush, createcachetable, loaddata)
  testdb.py             builds the pytest database nudge_test from the SQL files
Every module has the same folders (apps/accounts, apps/crm, apps/audit and common/health). File names and class names follow docs/CODING_STYLE.md, which wins over this file on names:
apps/accounts/  (same shape for crm, audit)
  api/            urls.py  <entity>_api.py (<Thing>Api classes): parse the request, call ONE service method, map the result
  dtos/           <feature>_dtos.py: strict request serializers and small response dataclasses of one feature together (auth_dtos.py)
  mappers/        <entity>_mapper.py: pure functions entity -> response DTO, only where the shape differs
  services/       <entity>_service.py  <entity>_validator.py (format rules only, never the database)  interfaces.py
  repositories/   interfaces.py (Protocols)  models.py (private ORM models)  <entity>_repository.py
  domain/         entities.py  enums.py  errors.py  defaults.py
  tests/          unit (services with fake repos), repo (real test DB), api (HTTP)
Never one big dtos.py or mappers.py: a test fails if a module has dtos.py, mappers.py, services.py or repositories.py, or a file name outside these patterns.

4. NO MAGIC STRINGS (common/messages.py)
- Every message is one line in class Messages(StrEnum), grouped by area. The member NAME is the stable error code and the VALUE is the English text, with {} where a value goes.
  Example: AUTH_BAD_CREDENTIALS = "That email and password do not match."   and   VALIDATION_TOO_LONG = "Use at most {} characters."
- Services raise errors by member: raise Unauthorized(Messages.AUTH_BAD_CREDENTIALS), or raise InvalidValue(Messages.VALIDATION_TOO_LONG, 80). Nobody writes a sentence in a service or controller.
- API error body: {"code": "AUTH_BAD_CREDENTIALS", "detail": "<text>"}; field errors have the same shape inside "fields". The frontend decides behaviour from the code, never from the text, so changing a text is a one-line edit in one file. Renaming a member changes the code on the wire and needs a frontend change.
- Texts must be unique (a repeated text would silently become an alias of the first member). @unique and a test enforce it.
- Same rule for: cookie names, header names, cache keys, audit actions, role names, status codes used in logic. They live in constants.py or enums.
- A test scans common/ and apps/ and fails the build when (a) a string literal is passed to an error class, or (b) any message name or message text appears as a string literal outside common/messages.py (tests are allowed to assert on literals: that pins the wire contract).
- Later translation (Urdu etc.) only touches messages.py.

5. DEPENDENCY INJECTION
- Constructor injection only. Example: AuthService(users: UserRepository, sessions: SessionRepository, hasher: PasswordHasher, tokens: TokenSigner, codes: VerificationCodeStore, audit: AuditWriter, clock: Clock).
- Depend on the Protocol, not the class.
- config/container.py builds everything. Controllers get their service from the container; tests build the same service with fakes.
- Scopes: singleton = settings, cache client, hasher, signer, rate limiter. Per-request = TenantContext and anything carrying it. Transient = services and mappers (new each time, stateless).
- No service locator inside services, no global state, no importing a repository class directly in a service.

6. ENTITIES, DTOs, MAPPERS
- Entity: frozen dataclass in domain/, represents a business object (User, Organization, Session). No framework imports.
- Request DTO: validated input from the client. Response DTO: exactly the fields the client may see. Never return an entity directly (no password hash, no internal ids).
- Mapper: row -> entity (repository), entity -> response DTO (api). Pure functions in the mappers/ folder, one file per entity, unit-tested.
- Client-computed fields (organization_id, role, version, created_at) are never read from the body.

7. REST CONVENTIONS
- /api/v1/<resource>/, nouns, plural. Status: 200, 201, 204, 400, 401, 403, 404, 409, 429, 503.
- JSON only. Body size limit, strict Content-Type, unknown fields rejected with 400.
- Success: resource or {"count","next","previous","results"} for offset pages, {"results","next_cursor"} for cursor pages.
- Query parameters parsed into ListQuery: allowed filters per resource, allowed sort fields, q (max 100 chars), page_size 1-100. Anything not on the whitelist is 400.
- Offset pagination for small lists (companies, contacts). Cursor (keyset) pagination for large ones (audit log, deals per stage, later inbox): cursor = base64 of (sort value, id), query uses WHERE (sort, id) < (x, y) LIMIT n+1.
- Search: parameterized ILIKE on indexed columns for now. Never string-build SQL.
- Optimistic concurrency: version / updated_at sent by client, 409 on mismatch with the current record in the body.
- Idempotent retries: PUT/DELETE safe; register/verify/resend return the same response for known and unknown emails.

8. RATE LIMITING (token bucket)
- Bucket per key (ip, user, email-hash): capacity C (burst), refill rate R tokens/second.
- On request: tokens = min(C, tokens + (now - last) * R); if tokens >= cost then tokens -= cost and allow, else reject with 429 and Retry-After = (cost - tokens) / R.
- Stored in Redis, one atomic Lua script per check (no race). Dev without Redis: in-memory version with the same interface.
- Policies live in constants.py: login 5 per minute per email-hash and 20 per minute per IP; verify 5 tries per code; resend 1 per 30 s; global API default 120 per minute per user.
- Headers: X-RateLimit-Limit, X-RateLimit-Remaining, Retry-After.
- Debouncing is a frontend job (wait about 300 ms after typing, cancel the older request). Server side: minimum and maximum q length plus the rate limit.

9. AUTHENTICATION AND SECURITY
Tokens
- Access token: JWT, 10 minutes, claims user_id, sid, jti. Sent as Authorization: Bearer, held in memory by the frontend.
- Refresh token: opaque random value in an HttpOnly, Secure, SameSite=Lax cookie, path /api/v1/auth/. Only its SHA-256 is stored (user_sessions). Rotated on every use; reuse of an old value revokes the session.
- Nothing can be hidden from the owner's DevTools. The goal is that page scripts cannot read the refresh token and the access token never touches storage.
Flows (first priority)
1. Register: validate, create user + organization + Owner membership + default stages in one transaction, send a 6-digit code by email (cache, 10 min, 5 tries). Same 202 response if the email exists.
2. Verify: check code, set email_verified_at.
3. Resend: 30 s limit, kills the previous code.
4. Login: unverified users get 403 email_unverified (only after a correct password). Success creates a session row, sets the cookie, returns the access token.
5. Refresh, logout, me, password change, forgot and reset.
Other protections (JWT alone is not enough)
- Authorization on every endpoint: role check in the controller, tenant filter in every repository query, 404 for other organizations' ids.
- Passwords: Argon2, 8-128 characters, common-password check, never logged.
- CSRF double-submit on cookie endpoints; strict CORS (frontend origin only, credentials on); security headers; HTTPS and HSTS in production.
- Parameterized SQL only. Input cleaned by common/text.py before validation.
- Same response and similar timing for known and unknown emails (dummy hash check).
- Sessions revoked on logout, password change and reset. Failed logins are audited (email hash only).
- Audit log for every security-relevant action. Secrets only in environment variables. pip-audit before release.
- Later: two-factor sign-in, Google and Microsoft sign-in, row-level security in the database (needs a schema change, so after the freeze).
Email
- Console backend in development; real SMTP when EMAIL_BACKEND names it in the environment (EMAIL_HOST, EMAIL_PORT, EMAIL_USE_TLS, EMAIL_HOST_USER, EMAIL_HOST_PASSWORD, DEFAULT_FROM_EMAIL, EMAIL_TIMEOUT), behind the EmailSender interface. Sent synchronously for the midterm; a background worker later. A strict sender raises 503 on failure; a quiet sender logs and swallows it (BACKEND_PLAN 9h).

10. TESTING PER LAYER
- services: unit tests with fake repositories (no database, no HTTP).
- repositories: against the test database built from the SQL file; one test per query including tenant isolation.
- api: HTTP tests for status codes, bodies, cookies, CSRF, rate limits.
- common: tests for messages (no duplicate codes), validators, pagination, token bucket (time faked).
- architecture test: services must not import django, rest_framework or psycopg; api must not import repositories; repositories must not import services.

11. BUILD ORDER (accounts first, one step at a time, each step reviewed by me before the next)
0  skeleton, settings split, environment, tooling
1  database connection, health check, migrate guard, test database from the SQL file
2  common: messages, errors, responses, constants, interfaces, text, validators, pagination, query, ratelimit (token bucket) with tests
3  accounts domain + repositories (users, organizations, memberships, sessions, default stages) with tests
4  accounts register + email code + verify + resend
5  accounts login, refresh, logout, me, csrf
6  password change, forgot and reset, sessions list
7  profile and organization (read, update)
8  audit write helper + audit log read
9  crm stages, then companies, contacts, deals
10 tenancy and N+1 sweep, API docs, seed_demo, production settings
Per step, the order of work is: design shown to me, interface (Protocol) first, tests, repository, service, controller, then run tests.

12. RULES FOR THE CODING ASSISTANT
- No code before the design for that step is approved.
- No magic strings; add the message or constant to common first.
- No schema change, no migrate, no git commit or push.
- One module and one layer at a time; show what changed.
