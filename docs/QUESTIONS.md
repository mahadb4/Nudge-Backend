# Questions

Each item gives the decision needed, my recommended default and the reason. Until you answer, the other docs assume the default.

## A. The ones you asked about

Q-1. Email verification: 6-digit code or link?
- Default: 6-digit code (the frontend is built for it).
  - Stored as an HMAC in the cache with a 10-minute TTL; 5 tries; resend after 30 s.
- Reason:
  - The /verify screen, its tests and the paste handling already exist.
  - Design proposal M1 already allows a code in Redis with no table.
- Sub-decision: the frontend waits 42 s before resend, design M1 says 30 s. Pick one (default 30 s, and change the frontend countdown).

Q-2. Maximum password length?
- Default: 128 characters, enforced on the server, measured in characters, never trimmed.
- Reason:
  - Matches the frontend.
  - It is well above NIST's minimum of 64.
  - It caps the cost of Argon2 on huge inputs.
- users.password varchar(128) holds the hash (about 100 characters), not the raw password, so it is not a limit.

Q-3. Google, Microsoft and SSO sign-in?
- Default: hide all three buttons in real mode for the midterm. Decide later between:
  - (a) django-allauth, which adds its own tables and breaks the 50-table rule;
  - (b) a custom OpenID Connect flow that only signs in an existing account whose email is verified by both sides. No table, but no stored provider id, so an email change at the provider can lock the user out.
- Reason: both options either add tables or carry a weaker account link. Neither is midterm scope.
- Mailbox connection (Gmail or Outlook OAuth for reading mail) is a separate feature and is unaffected.

Q-4. What replaces the 'Sign in' demo bypass?
- Default: a management command `python manage.py seed_demo`, dev and staging only (refuses when DEBUG is False). It creates:
  - one demo organization with the mock companies, contacts and deals from seed.ts;
  - a real verified user whose random password is printed once.
- The frontend hides the demo texts (sign-in credentials, demo code, 'Reset demo data') when not in mock mode.
- Reason:
  - A real login path, so no bypass code exists in production.
  - Demo data stays realistic for the presentation.

Q-5. Do editable deal stages need a table change?
- Answer: no. deal_stages (name, position, outcome) already supports add, rename, reorder and delete. The work is in the frontend, which must stop using the 7 fixed slugs.
- Decisions still needed (defaults from the frontend):
  - Won and Lost cannot be renamed or deleted.
  - Exactly one won and one lost stage.
  - The first stage stays first.
  - At most 12 stages.
  - Name limit 40 (column allows 60).

Q-6. Where do templates, approved facts, teams and per-reply-type automation live?
- Templates: email_templates.
  - name, body, subject (not in the UI).
  - Reply type = intent_label_id -> labels.
  - 'uses' = count of reply_drafts.template_id.
  - Visibility and owner as for CRM records.
- Approved facts: company_facts.
  - key -> title, value -> body, on -> is_active, by -> updated_by_id, when -> updated_at.
  - kind is NOT NULL and has no UI. Default: 4 Other until the form gets a kind picker.
- Teams: teams + team_members.
  - Many-to-many with is_lead. The frontend shows one team per member, so the API returns a list.
  - The team description in the UI has no column. Default: drop it from the UI.
- Per-reply-type automation: category_settings, one row per organization and label (mode 1 Never, 2 Approve first, 3 Automatic; min_score; hourly and daily caps).
  - 'Always ask me' on = mode 2, off = mode 3.
  - Opt-out and Unclear are refused as mode 3 on the server.
- Not in the schema:
  - the global mode 'Draft-only / Act when sure';
  - the single confidence bar (85).
  - Default: derive the global mode as "any category in mode 3", and show the bar as the min_score shared by all categories, kept equal by the API.
  - Alternative: approve design proposal M9 (one smallint on organizations).
- All four are later, not midterm.

## B. Schema, setup and tooling

Q-7. Django's own tables.
- contrib.auth and contenttypes create django_migrations, django_content_type, auth_permission, auth_group and auth_group_permissions.
- PermissionsMixin adds users_groups and users_user_permissions.
- Admin and sessions add django_admin_log and django_session.
- None of these are among the 50.
- Default: never run `migrate` on the nudge database; no Django admin; no PermissionsMixin. Superuser checks use users.is_superuser. pytest builds its database from the SQL file.
- Alternative: allow the 5 auth/contenttypes tables and the 2 admin tables if you want the Django admin.
- Reason: this keeps exactly 50 tables.

Q-8. Can an unverified user sign in?
- Default: no. 403 {"code": "email_unverified"}; the frontend sends them to /verify and resends a code.
- Reason: the frontend's flow already assumes verify before onboarding.

Q-9. Token lifetimes.
- Default:
  - access 10 minutes;
  - refresh 30 days with 'Keep me signed in';
  - otherwise a browser-session cookie with a 1-day server expiry;
  - no idle timeout beyond that.
- Reason: matches the '30 days' text; short access lifetime plus per-request session check gives fast revocation.

Q-10. Extra packages beyond the fixed list.
- Default:
  - argon2-cffi: Argon2 hashing, required by the design (Req 1.4).
  - redis + Django's built-in RedisCache: throttles and verification codes shared across processes. Local Redis in dev, or LocMemCache with a single process for the midterm only.
  - pip-audit (dev only).
- Reason:
  - DatabaseCache would need a new table.
  - LocMemCache is per process, so rate limits would not hold in production.

Q-11. Currencies.
- organizations has no currency column (design P1 says 'set from the organization').
- Default:
  - the server accepts every active ISO 4217 code from a fixed list in code;
  - the deal form sends the currency explicitly;
  - the default in the form comes from the browser locale;
  - the 'Default currency' field in Workspace settings is removed.
- Alternative: add organizations.currency (schema change).

Q-12. Phone numbers without '+'.
- Default: the server requires international format (+ and country code) and normalises to E.164 with phonenumbers.
  - Profile: the country-code select supplies the prefix and becomes a full country list.
  - Contacts and CSV: a number without '+' is refused.
- Reason: there is no organization or user country column to guess a region from.

Q-13. Which SQL file is in your local database: nudge_schema_v3_1.sql (pgvector) or nudge_schema_v3_1_no_pgvector.sql?
- Default: the no-pgvector file for local and tests.
- Reason: only email_chunks (FYP-II) differs, and pgvector is often missing on Windows installs.

Q-23. Python version and UUIDv7.
- Default: Python 3.14 (uuid.uuid7() is built in).
- If you are on 3.12 or 3.13: either add the uuid-utils package, or let the database default nudge_uuid_v7() fill the id (Django 5.2 db_default, read back with RETURNING).
- Reason: ids must be UUIDv7, as the schema expects.

Q-27. May I add indexes (not tables or columns) when a screen needs them, e.g. pg_trgm trigram indexes for contact and company search?
- Default: no new indexes for the midterm; ILIKE search capped at 100 characters. Ask again with numbers if a list gets slow.

Q-28. The docs you listed are not on disk: CLAUDE.md, nudge_validation_spec_v3_1.md, nudge_normalization_v3_1.md, nudge_backend_plan.md. The SQL file is only in D:\Downloads.
- Default:
  - you copy nudge_schema_v3_1.sql (and the no-pgvector variant and nudge_seed.sql) into Nudge-Backend/docs/;
  - you send the other four files if they exist, so I can re-check GAP_REPORT section 3 and BACKEND_PLAN section 6 against the validation spec.

## C. Rules the docs do not settle

Q-14. Contact names and email.
- The frontend has one name field. The schema has first_name (NOT NULL) and last_name.
- Default: the API takes first_name and last_name and returns a read-only name; the form gets two fields.
- Alternative: the API takes name and stores it all in first_name with last_name null. No split guessing, but sorting by last name (ix_contacts_2) is lost.
- Email: required by the frontend, nullable in the DB. Default: required in the API too for manual creation; optional only for contacts made from email or forms later.

Q-15. Concurrency and delete for companies and contacts.
- They have no version column.
- Default: use updated_at as the version (client sends what it read; 409 on mismatch).
- Delete is soft (deleted_at). Restore endpoint (30-day restore per design): later.

Q-16. Company uniqueness.
- The frontend refuses a duplicate name; the DB refuses a duplicate domain (design open decision D13).
- Default: enforce both on the server (name ignoring case among live rows, domain by the index).

Q-17. Who may remove an opt-out?
- Default: Owner and Admin only, audited.
- Reason: re-contacting someone who asked to stop is a legal risk.
- Alternative: nobody (opt-out is permanent).

Q-18. Deal amount and links.
- The DB allows a null or 0 amount; the frontend requires > 0. Default: required, > 0.
- If both company and contact are given, must the contact belong to that company? Default: no hard rule (contacts move between companies); the UI keeps filtering.
- Lost reason: one of the 5 frontend reasons, or free text 1-200? Default: free text 1-200; the UI offers the 5 as choices.

Q-19. Who may see the audit log?
- Default: Owner and Admin.
- Reason: it includes logins and role changes. The frontend shows it to everyone.

Q-20. Default visibility and the Manager role.
- The DB default is 1 Private. With that, a Member's new records are invisible to other Members, but the UI assumes everyone sees everything (design D11 is open).
- Default:
  - the API sets visibility 3 Organization on create unless the request says otherwise;
  - Manager behaves as Member until you define it.

Q-24. Undo after approve.
- The frontend says 7 days; the design says a 10-minute hold before sending (send_after, REQ-SF-03).
- Default: 10 minutes; change the toast text.
- Reason: once an email is sent it cannot be undone.

## D. API style

Q-21. API docs in production.
- Default: /api/v1/schema/ and /api/v1/docs/ only when DEBUG is True, or for is_staff users in production.

Q-22. How the current organization is chosen.
- Default: X-Organization-ID header, falling back to the only membership.
- Reason: stateless; no new token on workspace switch; the midterm frontend works without sending it.
- Alternative: an org claim in the access token, re-issued by POST /auth/switch-organization/.

Q-25. Error format and login failure status.
- Default:
  - 400 keeps DRF's {field: [messages]};
  - other errors are {"code", "detail"};
  - wrong login is 401 bad_credentials.
- This needs the frontend change in BACKEND_PLAN section 8 item 4, because the client now treats every 401 as an expired session.
- Alternative with no frontend change: wrong login as 400 {"non_field_errors"}. The UI would then show 'Check the highlighted fields' instead of 'That email and password do not match.'

Q-26. Field names on the wire.
- Default: snake_case. Frontend names where they map 1:1 to a column (deal name, contact title); column names where the frontend uses display text (expected_close_date, created_at); codes as lowercase strings.
- Reason: the client's error parser accepts only [a-z_] keys.
- Alternative: camelCase through a renderer package (another dependency).

Q-29. Frontend changes.
- BACKEND_PLAN section 8 lists 14 changes in the frontend repo. Do you make them, or do I, in a separate task with the same git rules?
- Default: I do them in a separate task after the auth endpoints pass their tests.

Q-30. Which limit wins when the frontend is stricter than the column (name 80 vs 150, deal name 80 vs 150, stage 40 vs 60, title 80 vs 100)?
- Default: the frontend limit, so the API and UI give the same answer. The column is only the ceiling.

## E. Later, no answer needed for the midterm

- D9 'Other' as a 10th reply type: labels has it; the UI has 9.
- Design proposals H3 (suggested_actions table), H4 (reply_drafts for compose and follow-ups), M9 (organization automation mode), M10, M12, M13 are needed for Review, compose, follow-ups, calendar and integrations to match the UI.
- Background job runner (the proposal says Celery + Redis) for mail sync, sending and CSV import.
- Email sending provider for verification codes and reset links outside dev. Dev uses Django's console email backend.
