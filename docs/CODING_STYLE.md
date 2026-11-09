NUDGE CODING STYLE v1
Based on the Student Management project (docs/reference/STYLE_REFERENCE_student_project.md), with its known weaknesses fixed.
This refines docs/ARCHITECTURE.md. If the two disagree on security or layering, ARCHITECTURE.md wins. If they disagree on file names or naming, this file wins.
Do not read the student reference file in full; it is 3000 lines. Open it only when a question about the old style comes up.

0. WHY THESE LAYERS (so they can be defended, and so they are not copied blindly)
Plain Django is models + views, and DRF serializers. Repository, service and mapper layers come from clean architecture. We use them in Nudge for three concrete reasons, not for decoration:
- The tables are unmanaged and every query must be filtered by organization. The repository is the one place that rule cannot be forgotten (tenant safety).
- Performance-critical queries are hand-written parameterized SQL; they need a home.
- Services can be unit-tested with fake repositories, without a database or HTTP.
Do not add a layer or a file that does not earn its place. The student project's habit of one DTO file per shape and one mapper per DTO is NOT copied.
Scalability comes from the rules in section 7, not from the folder structure.

1. MODULE LAYOUT AND FILE NAMES (close to the student project, but lighter)
apps/<module>/
  api/            urls.py, <entity>_api.py          HTTP only: APIView classes named <Thing>Api
  dtos/           <feature>_dtos.py                 request serializers (strict) and small response dataclasses for one feature together, e.g. auth_dtos.py; not one file per class
  mappers/        <entity>_mapper.py                pure functions entity -> response DTO; only where the shape differs from the entity
  repositories/   <entity>_repository.py            all database access
  services/       <entity>_service.py, <entity>_validator.py
  cache/          <entity>_cache.py                 later, after the midterm
  domain/         entities.py, enums.py             frozen dataclasses
  tests/          test_<topic>.py
File names are <entity>_<role>.py (dtos use <feature>_dtos.py). Classes are PascalCase: UserService, UserRepository, UserValidator, RegisterRequest, MeResponse. Mappers are plain functions, not classes with static methods.

2. LAYER RULES
api          reads the request into a request DTO, calls ONE service method, maps the result with a mapper, returns the response. No rules, no SQL, no try/except ladders.
service      business rules and orchestration, in this order: validator (format only) -> checks that need the database (uniqueness, existence) -> repository -> audit write -> cache invalidation. Raises AppError subclasses only, never ValueError, never HTTP objects.
validator    <entity>_validator.py: format and range rules only. It never touches the database (the student project did; do not copy that). It uses the functions in common/validators.py and raises InvalidValue.
repository   the only code that touches the database. Returns entities. Soft delete and the organization filter live in the base repository.
dto/mapper   dataclasses, no logic beyond copying fields. Never return an entity or a database row from the API.
Services and repositories are wired by constructor injection in config/container.py (the student project did it at module import time in every api file; do not copy that).

3. COPY THESE FROM THE STUDENT PROJECT
- One Messages class, one line per message, grouped with banner comments (# -- Auth ----). In Nudge it is a StrEnum: Messages.AUTH_BAD_CREDENTIALS. The error code sent to the client is the member name; the text is the value; {} placeholders use .format().
- Service flow order (section 2).
- Repository method names: get, get_all, get_queryset_for_list, name_exists(name, exclude_id=None); services: get, get_list, create, update(id, data, partial=False), delete; private helper _merge_data.
- Per-repository ORDERING_FIELDS allowlist and DEFAULT_ORDERING, with id as the tie-breaker so pages are stable.
- Search: split on spaces, every word must match some field (case-insensitive), as parameterized SQL.
- Pagination helper that normalises page and page_size first, then queries.
- BaseEntityCache and CacheService idea for list caching (after the midterm). Cache keys must include the organization id.
- Constants in common/constants.py, all user text in common/messages.py, UPPER_SNAKE constants.

4. DO DIFFERENTLY (the student project's own improvement list)
- Use DRF APIView classes, one method per HTTP verb. No if request.method ladders.
- Typed errors (AppError subclasses) and one global exception handler. No ValueError for business errors; unexpected exceptions become a JSON 500 that leaks nothing.
- Request DTOs with strict validation (unknown fields rejected). No raw dict requests; a missing key is a clean 400, never a KeyError 500.
- DTOs are @dataclass classes with a to_dict() helper (asdict). No hand-written __init__ that repeats every field three times.
- Validators never query the database.
- No hard-coded passwords, no text such as "(deployment test)" in messages, no bare except Exception.
- One authentication class (JwtAuthentication) used everywhere. No copied JWT blocks.
- Rate limiting on login, register, verify, resend and reset from the first day.
- CSRF is enforced on cookie endpoints (the student project used csrf_exempt everywhere because it used only Bearer tokens).
- JWT lifetimes set explicitly; refresh tokens rotate and are stored only as a hash (user_sessions); no token blacklist table.
- Tests per layer from the start: service with fakes, repository on the test database, api over HTTP, plus the architecture test.

5. CODING CONVENTIONS
- Standard PEP 8 formatting (keyword arguments without spaces around =, like status=201). This differs from the student project on purpose, so tools such as ruff can format the code.
- Type hints on every function signature.
- No docstring walls. A short # comment above the code, explaining WHY, when the reason is not obvious.
- Soft delete uses deleted_at (the Nudge columns), not is_deleted.
- HTTP status codes come from named constants, not scattered literals.
- API responses: success is the resource or the page envelope; errors are {"code","detail"} plus fields or current. Do not use {"error": "..."}.
- Page envelope for offset lists: {"count","next","previous","results"} (the Nudge API_CONTRACT wins over the student project's total_count/current_page shape).

6. HOW A REQUEST MOVES (example: POST /api/v1/auth/login/)
LoginApi.post -> LoginRequestDto (strict) -> LoginService.login(dto, ip) -> UserValidator (format) -> UserRepository.get_by_email -> hasher.verify -> SessionService.start -> AuditWriter.write -> AuthMapper.to_me_response -> LoginResponseDto -> Response (access token in the body, refresh token in an HttpOnly cookie).
Messages used by the service: Messages.AUTH_BAD_CREDENTIALS, Messages.AUTH_EMAIL_UNVERIFIED, etc. Only messages.py contains sentences.

7. SCALE RULES (what actually lets the system grow; checked in code review and tests)
- Stateless API: no data kept in process memory between requests. Anything shared (codes, rate limits, caches) lives in Redis or the database. Any number of API copies must behave the same.
- No unbounded queries: every list is paginated with a hard page-size cap (100). Large or growing lists (audit log, deals per stage, inbox) use keyset (cursor) pagination, never deep offsets.
- No N+1: lists load related data with joins or one grouped query; each list endpoint has a query-count test.
- Search and filters use columns that have an index; a new filter needs its index checked before merging.
- Cache keys include the organization id. No wildcard deletes (no KEYS or SCAN delete_pattern); invalidate with versioned keys: each cache namespace holds a version number, a write increments it, old keys expire by TTL.
- Slow or failure-prone work (sending email, mailbox sync, ML, AI calls) never runs inside the request path once it exists: it goes to a background worker through a queue. Until the queue exists, such work sits behind an interface (EmailSender, etc.) so it can be moved without touching services.
- Writes that can be retried are idempotent (idempotency keys, conditional updates with version checks).
- Database access goes through a connection pool; every query has a timeout; transactions are short, and nothing slow (network calls) happens inside a transaction.
- Every external call (email, AI, providers) has a timeout and a retry policy with a limit.
- Configuration only from environment variables; secrets never in code or logs.
- Structured logging with a request id on every line; no passwords, tokens, codes or email bodies in logs.
- Rate limiting on every public or expensive endpoint; the limiter fails closed for auth endpoints.
- Health endpoint for the load balancer; graceful errors (503) when the database is down.
- Later (documented, not midterm): read replicas for heavy reads, partitioned audit log by month (the design already allows it), a separate worker process for mail and ML, extracting a module into its own service only when its load or team requires it.
