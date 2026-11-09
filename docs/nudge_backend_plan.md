NUDGE BACKEND: START GUIDE (Windows, VS Code, Claude extension)

PART 1. ONE-TIME SETUP (about 20 minutes)

1. Make the repo
   mkdir nudge-backend
   cd nudge-backend
   git init
   mkdir docs
   Copy into docs/: nudge_schema_v3_1_no_pgvector.sql, nudge_db_design_v3_1.md, nudge_validation_spec_v3_1.md, nudge_normalization_v3_1.md
   Copy CLAUDE.md into the repo root (VS Code Claude reads it automatically).

2. Python environment (Python 3.12 recommended)
   python -m venv .venv
   .venv\Scripts\activate
   pip install "django==5.2.*" djangorestframework PyJWT psycopg[binary] django-environ phonenumbers pytest pytest-django django-cors-headers drf-spectacular
   pip freeze > requirements.txt

3. Create the project
   django-admin startproject config .
   python manage.py startapp accounts
   (move apps into an apps/ folder later if you want)

4. .env (do not commit; add .env to .gitignore)
   DATABASE_URL=postgres://postgres:YOUR_PASSWORD@localhost:5432/nudge
   SECRET_KEY=any-long-random-string
   DEBUG=True

5. Test database for tests
   In pgAdmin create database nudge_test, then run the same SQL file on it.

PART 2. THE ORDER OF WORK (each step = one prompt to Claude in VS Code)

Step 1  Settings + database connection + inspectdb draft of all 50 models (managed=False). Check: python manage.py check passes, and a shell query on Organization works.
Step 2  Constants: IntegerChoices for every smallint code, from the design doc. Check: each CHECK in the SQL has a matching choice.
Step 3  Auth: custom User (db_table users), signup, email verification, login (JWT), refresh, logout, password change, forgot/reset. Validation exactly per the validation spec for users.
Step 4  Organization + membership: create org on signup, current organization on every request (middleware/mixin), profile read/update (name, phone E.164, time zone, locale).
Step 5  Tenant base: TenantViewSet mixin + tests that cross-organization access returns 404.
Step 6  CRM CRUD: stages (seed through nudge_create_default_stages), companies, contacts, deals. Soft delete, search, filters, pagination, deal optimistic concurrency (version, 409).
Step 7  Audit log writes for create/update/delete actions.
Step 8  API docs (drf-spectacular) so the frontend can be derived from it.
Then: email accounts and ingestion, classification pipeline (after midterm).

PART 3. PROMPTS TO PASTE

Prompt for Step 1:
Read CLAUDE.md and docs/. Configure Django settings for PostgreSQL database nudge using django-environ, then run inspectdb against it and create managed=False models for all 50 tables, grouped into apps accounts, organizations, crm, email, ai, audit. Do not run migrate for our tables. Show me the list of apps with their tables before writing files, and wait for my OK.

Prompt for Step 2:
Create constants.py per app with IntegerChoices for every smallint code column. Take the exact numbers from docs/nudge_db_design_v3_1.md and the CHECK constraints in the SQL file. List any column where the meaning of a code is unclear instead of guessing.

Prompt for Step 3:
Implement authentication in the accounts app: custom User on table users (managed=False), signup, email verification by link (console email backend in development), login and refresh with PyJWT, password change, forgot and reset password. Apply the users section of docs/nudge_validation_spec_v3_1.md. Write pytest tests for every rule. Ask me before choosing anything the SRS or the validation spec does not state (for example maximum password length).

Prompt for Step 4:
Implement organization creation at signup, memberships, the request.organization resolution, and the profile endpoint. Follow the validation spec for phone (E.164), time zone (IANA) and currency (ISO 4217).

Prompt for Step 5:
Create a TenantModelViewSet base class that filters every queryset by request.organization and sets organization_id on create. Add tests proving cross-organization reads, updates and deletes return 404.

Prompt for Step 6:
Implement CRUD for stages, companies, contacts and deals following the validation spec and the design doc. Soft delete for companies, contacts and deals. Deals use the version column for optimistic concurrency and return 409 on conflict. Include list filters, search and pagination.

GOOD HABITS
- One step per prompt, run the tests, commit, then the next step.
- If Claude suggests adding a column or table, say no and ask me; the database is frozen for the midterm.
- Keep a short file DECISIONS.md in the repo for every open decision you settle (password length, verification link vs code, etc).

OPEN DECISIONS (defaults I will assume unless you say otherwise)
1. JWT library: PyJWT (SimpleJWT was removed on 9 Nov 2026).
2. Email verification: link, not 6-digit code.
3. Password: minimum 8 with letters and numbers; maximum to be decided (64 or more recommended, not 50).
4. Django maps to the existing tables as unmanaged models; the SQL file stays the single source of truth.
