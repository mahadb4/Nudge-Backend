# Gap report: frontend screens against the backend that exists (10 Nov 2026)

Written on 10 Nov 2026. Read only: no code was written or changed for this report.
Sources:
- Frontend: D:\Desktop\Nudge-frontend (src/App.tsx, src/pages, src/store.ts, src/data/seed.ts, src/api).
- Backend: the endpoints listed in CLAUDE.md "Current status" and docs/API_CONTRACT.md.
- The older schema-level gap list (tables and columns the frontend needs that the schema lacks, ids G-A1 to G-A20) moved, unchanged, to docs/GAP_REPORT_SCHEMA.md. The ids G-A* quoted in other docs point there.

## What is wired today

Only authentication is wired to the real API (src/api/auth.ts, real mode is the default). Every other screen reads and writes an in-memory store that `hydrateWorkspace()` fills with `src/data/seed.ts` after sign-in. So "ready to wire" below means: the endpoint exists and works, and the screen still uses the mock store.

Backend endpoints that exist: health, csrf, register, verify, resend, login, refresh, logout, me (GET, PATCH), password change, reset, reset confirm, organizations/current (GET, PATCH), deal-stages (list, create, rename, reorder, delete), companies (list, get, create, update, delete), contacts (list, get, create, update, delete).

Rules that apply to every screen below (frontend work, not backend):
- Send `X-Organization-ID` once a user can have several organizations (today the demo user has one, so it is optional).
- PATCH companies and contacts must send back the `updated_at` they read (409 `COMMON_VERSION_CONFLICT` otherwise).
- Lists are paginated (page_size at most 100). The mock screens filter the whole list in the browser; the wired screens must page or ask the server (`q`, filters) instead.
- Money is a per-currency list, never one number.

## List 1. Screens whose data already has a working endpoint (ready to wire)

| Screen | Endpoint | Fields the screen shows that the API does not return (or needs changed) |
|---|---|---|
| Sign up, Verify, Sign in, Reset, New password, sign out, session restore (`/sign-up`, `/verify`, `/sign-in`, `/reset`, `/new-password`) | Already wired: register, verify, resend, login, refresh, logout, reset, reset/confirm, me | Nothing missing. `MeDto` in src/api/client.ts reads only name, email, type, verified; `me` also returns phone, timezone, quiet hours, organization, role, organizations (unused so far). |
| App shell: top bar workspace name and switcher, account menu | GET /auth/me/ (`organization`, `organizations`, `role`, `name`, `email`) | The switcher shows a hard-coded "Acme Sales". "New workspace" has no endpoint (stays a toast). |
| Settings > Security > Password | Already wired: POST /auth/password/ | Nothing missing. After a change the other devices are signed out (the mock "Active sessions" list does not reflect that). |
| Settings > Profile | GET and PATCH /auth/me/ | Email is hard-coded in the form (use `me.email`). Phone: the form has a country-code select plus digits, the API wants one E.164 string (`+923005550142`) and refuses a number without `+`. The time-zone select lists 4 zones; the API accepts any IANA name. |
| Settings > Workspace: name, time zone | GET and PATCH /organizations/current/ | The "Default currency" select has no backend (removed by decision Q-11; the frontend still shows it). The form has one time-zone select; the API has two (user and organization). |
| Settings > Workspace: Quiet hours | PATCH /auth/me/ (`quiet_hours_start`, `quiet_hours_end`) | The UI stores text like "8:00 PM"; the API wants "HH:MM" on a 24-hour clock, both set or both null (the on/off toggle = both null). They are a per-user setting shown inside the workspace tab. |
| Settings > Workspace: Deal stages editor, Onboarding step 4 does not use it | GET, POST, PATCH, PUT order, DELETE /deal-stages/ | The editor edits a whole list and saves once; the API is one call per change (rename, add, delete, reorder), so the Save button must diff and call. Won and Lost fixed, 40-character names, first stage not movable: the UI rules already match. The API also returns `deal_count` per stage (not shown). |
| Companies list (`/app/companies`) | GET /companies/ (`q`, `ordering`, `owner_id`, pages) | Not returned: **location**, **website** (only `domain`). Search by location is not possible. "Open value" shows USD only; the API returns one total per currency. The page filters in the browser; it must use `q` and paging. |
| Add company | POST /companies/ | The form sends name, domain, industry; the API also takes size_range, owner_id, visibility, team_id. 409 `CRM_COMPANY_NAME_TAKEN` / `CRM_COMPANY_DOMAIN_TAKEN` replace the local duplicate check. |
| Company detail > About and People | GET /companies/{id}/, GET /contacts/?company_id= | Not returned: **location**, **website**. Size shows as "1-10" style text. Owner comes as `{id, name}`. |
| Contacts list (`/app/contacts`) | GET /contacts/ (`q`, `status`, `owner_id`, `company_id`, `ordering`, pages) | Not returned: **location**, **Suspended** status (API has active and opted_out only), **last contact** (always null until mail exists). The owner filter lists hard-coded names; the API filters by `owner_id` and there is no endpoint yet to list owners (see list 2, members). The form has one full-name field; the API has first_name and last_name (split in the frontend). Title is called `title` in the API. |
| Add contact (and "Add person" on a company) | POST /contacts/ | Email is required (the form already requires it). The 409 `CRM_CONTACT_EMAIL_TAKEN` can carry `existing` to link to the other contact. Phone must be E.164 with `+`. |
| Contact detail > Profile | GET /contacts/{id}/ (PATCH for edits, DELETE) | Not returned: **location**, **last contact**. There is no edit form in the UI yet. |
| Import CSV (contacts) | POST /contacts/ once per row (frontend loop) | The server-side import endpoint is "later"; a loop is possible for the 500-row limit but slow (see list 2). Export CSV is client-side and would only cover the loaded page. |

## List 2. Screens that need a backend endpoint that does not exist yet

Size guesses are for one developer who already knows the module patterns: small = under half a day, medium = about a day, large = more than a day.

### Needed for the midterm

| Screen / feature | Endpoint needed | Size | Why it is needed |
|---|---|---|---|
| Contact detail: "Mark opted out" / "Remove opt-out" and the amber banner | POST and DELETE /contacts/{id}/opt-out/ (DELETE is Owner/Admin only, Q-17) | small | In the contract as [midterm]; the button is on the contact screen of the demo path. The `status` field and filter already read `opted_out_at`. |
| Owner filters and owner pickers (Contacts, Pipeline, Add deal); Settings > Team people list | GET /members/ (read only) | small | The screens use hard-coded owner names. Without it a user cannot filter by anyone but themselves. |
| Settings > Team > Teams box | GET /teams/ (read only) | small | Shows team names and members; also what "team" visibility needs to be usable in the UI. |
| Pipeline board, Add deal, Mark as lost, Deal detail, "Deals" lists on company and contact detail, Home "Open pipeline" numbers | /deals/ list, create, get, update with `version`, delete, move stage (with lost reason), /deals/summary/ | large | Whole pipeline screen group; also the deals half of the company and contact pages and the numbers on Home. Needs the version check, closed_at rules, currency per deal. |
| Settings > Security > Active sessions | GET /auth/sessions/, DELETE /auth/sessions/{id}/ | small | [midterm] in the contract; the list is mock today. Location text ("Karachi, PK") has no source (GeoIP is later). |

### After the midterm

| Screen / feature | Endpoint needed | Size | Note |
|---|---|---|---|
| Settings > Audit log (read, filter, export) | GET /audit-logs/ (Owner/Admin, cursor pages) | medium | The rows are already written by every write. The screen shows "who" as a name and "on" as a label; `details.label` covers "on". |
| Review (approve, reject with reason, skip, edit draft, suggested actions, facts used) | /reviews/ list, approve, reject, skip, reply type change | large | Needs reply_drafts, predictions and the ML pipeline; several columns are schema gaps (G-A7). |
| Inbox (threads, messages, "New email") | /threads/, /messages/, send | large | Needs mailbox sync and email_threads/messages. |
| Mailboxes (connect Google or Microsoft, reconnect, disconnect) and onboarding step 1 | OAuth start/callback, /mailboxes/ | large | Gmail/Graph OAuth, token storage. |
| Settings > Approved facts and onboarding step 2 | /facts/ CRUD | medium | company_facts exists; `kind` is not on the screen (default 4). |
| Templates | /templates/ CRUD | medium | email_templates exists; "uses" is a count of drafts. |
| Follow-ups | /follow-ups/, snooze, done, send | medium | follow_ups exists; sending depends on the email pipeline. |
| Calendar (events, "Confirm hold") | /meetings/ | large | G-A11: no "hold" status. |
| Settings > Automation (mode, confidence bar, per-type) and onboarding step 3 | /settings/automation/ | medium | Schema gap M9: no organization column for global mode or one threshold. Needs a schema decision first. |
| Settings > Notifications | /notifications/settings/ | medium | G-A10: the screen is per event, the table is per channel. |
| Settings > Integrations (Slack, Calendar, Webhooks, HubSpot) | several | large | Schema gap M13. |
| Settings > Team: invite, change role, remove, resend | /invitations/, PATCH/DELETE /members/{id}/ | medium | Needs the last-owner rule and invitation emails (the sender exists). |
| Settings > Security > Two-step sign-in | TOTP setup and verify | large | G-A9: no column for the secret. |
| Agent chat (page and side panel) | /assistant/ conversations | large | FYP-II tables. |
| Home dashboard (waiting count, approved today, week bars, reply-type mix), Reports | /dashboard/, /reports/ | large | Mostly derived from reviews and predictions; the pipeline half can reuse /deals/summary/. |
| Command palette search (people, deals, emails) | search over contacts, deals, threads | medium | Contacts and companies can already be searched with `q`; deals and emails cannot. |
| Contact "location", "Suspended", "last contact"; company "location", "website" | none | not a backend task | G-A3: no columns. Remove from the screens, or take a schema decision. |

## List 3. Recommended order for the next four days (10 to 13 Nov; 14 Nov is the buffer and the demo)

Demo path: sign up, sign in, profile, organization, stages, companies, contacts. Everything on that path already has an endpoint, so the first two days are frontend wiring with only small backend additions on the side.

| Day | Frontend wiring (the other window) | Backend (this repository) |
|---|---|---|
| **Mon 10 Nov** | Run `seed_demo` on the real nudge database. Switch the shell to `GET /auth/me/` (name, workspace name). Wire Settings > Profile (PATCH /auth/me/, E.164 phone) and Settings > Workspace (organization name and time zone, quiet hours, remove the currency select). Add a small typed API module for the crm calls (CSRF is not needed for bearer calls). | Contact opt-out and opt-in endpoints (small). Read-only /members/ and /teams/ (small). Fix anything the first real wiring reveals. |
| **Tue 11 Nov** | Wire the stage editor (diff then call), Companies list and add (server `q`, paging, 409 messages), Company detail (About, People). | Start deals: model, repository, list, get, create, update with `version`, delete, move stage with lost reason and closed_at (the largest piece). Real-mode CSRF/refresh issues from wiring come first. |
| **Wed 12 Nov** | Wire Contacts list, add, detail, opt-out toggle, owner filter from /members/; CSV import as a loop; split full name into first and last. | Finish deals: /deals/summary/, visibility, cross-organization tests, audit; add deals and teams to `seed_demo`; optional sessions list endpoints (small). |
| **Thu 13 Nov** | Wire Pipeline board, Add deal, Mark lost, Deal detail, the deals lists on company and contact pages, Home pipeline numbers. Everything else (Review, Inbox, Mailboxes, Facts, Templates, Follow-ups, Calendar, Agent, Reports, Automation, Notifications, Integrations) stays on mock data, labelled as a preview. | Bug fixing, query-count and tenant checks on deals, doc updates, review zip. |
| **Fri 14 Nov** | Buffer and demo rehearsal: sign up, verify, sign in, edit profile, rename the organization, edit stages, add a company and a contact, open the pipeline. | Buffer. No new features. |

Risks to watch:
- If deals slip, the demo path (sign up to contacts) still works; the Pipeline screen would stay on mock data.
- Wiring is the first time the real API meets the real UI: expect small contract differences (field names, error codes). Budget the first half of each day for them.
- The demo user must be created with `seed_demo` on the real database by the user (the backend work never runs it).
