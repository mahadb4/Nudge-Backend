# Frontend scan

Source: D:\Desktop\Nudge-frontend (commit cd82c70). React 19, react-router-dom 7, no state library (src/store.ts is a small external store).
Everything below is what the code does today. All data is mock data from src/data/seed.ts, loaded into memory by hydrateWorkspace() after sign-in and wiped by clearWorkspace() on sign-out or any 401.

## 0. Cross-cutting

API client (src/api/client.ts)
- Base URL from VITE_API_URL. Empty = mock mode, no network calls.
- Every call: credentials 'include', cache 'no-store', redirect 'error', 15 s timeout.
- Unsafe methods send X-CSRFToken read from the csrftoken cookie.
- Optional Bearer token held in memory (setAccessToken). Nothing in localStorage or sessionStorage except theme and the mock demo flag.
- Status mapping: 401 -> clears token, calls onUnauthorized (wipes store, goes to /sign-in with notice 'expired'); 403 forbidden; 404 not_found; 429 rate_limited (reads Retry-After); 400/422 invalid (keeps only top-level body keys matching /^[a-z_]{1,40}$/, max 10, as field names); other -> server. Server text is never shown.
- Paths must match /^\/[A-Za-z0-9_\-./]*(\?[A-Za-z0-9_\-=&.]*)?$/.
- Only auth endpoints exist in src/api/auth.ts. Every other screen calls store functions on mock data.

Auth endpoints the client already calls (real mode), relative to VITE_API_URL:
| Call | Method, path | Body sent | Expected response |
|---|---|---|---|
| login | POST /auth/login/ | {email, password, remember} | User |
| register | POST /auth/register/ | {name, company?, email, password, type} | nothing |
| verifyEmail | POST /auth/verify/ | {email, code} | User |
| resendCode | POST /auth/resend/ | {email} | nothing |
| requestReset | POST /auth/reset/ | {email} | nothing |
| resetPassword | POST /auth/reset/confirm/ | {token, password} | nothing |
| changePassword | POST /auth/password/ | {current, password} | nothing |
| me | GET /auth/me/ | none | User, or 401 = signed out |
| logout | POST /auth/logout/ | none | ignored |
| oauth | none in real mode (throws) | | |

User shape: {name: string, email: string, type: 'Individual' | 'Business', verified: boolean}

Route guards (src/components/guards.tsx)
- RequireAuth: if no user in memory, calls api.auth.me() once; signed out -> /sign-in with state.from.
- SessionWatcher: wires 401 handler; reloads page on back/forward cache restore after sign-out.
- useSubmit: blocks double submit on auth forms.
- idOk(): route ids must match /^[A-Za-z0-9_-]{1,64}$/ (UUIDs pass).

Shared rules (src/data/validate.ts). LIMITS: name 80, email 254, company 120, title 80, phone 20, subject 200, body 5000, password 128, note 1000, stage 40, fact 200, domain 253, search 100, chat 500, amount < 1,000,000,000,000.
- clean(): NFC, strip C0/C1 controls (except tab/newline) and DEL, strip zero-width/bidi characters, collapse whitespace, trim. cleanMulti(): same but keeps line breaks, CRLF -> LF.
- normEmail(): strip, trim, lowercase.
- emailOk(): <= 254, local part <= 64, no '..', no leading dot, no trailing dot in local part, ASCII regex, TLD letters only, at least 2 letters.
- nameErr(v, what, min=2, max=80): length after clean(), no < or >.
- personErr(): nameErr + must contain a letter (\p{L}).
- passwordErr(p, {email, name}): 8 to 128, no control chars, upper + lower, a digit, must not contain email local part (if >= 4 chars) or any name word of >= 4 letters, not in a 27-word common list (after removing trailing digits/symbols), not one repeated char, not starting with 0123/1234/2345/3456/abcd when shorter than 10. Never trimmed.
- amountErr(): commas removed, /^\d+(\.\d{1,2})?$/, > 0, < 1e12.
- phoneErr(): optional; after removing spaces, brackets, dashes: /^\+?\d{7,15}$/.
- domainErr(): optional; lowercase host name, labels 1-63 without leading/trailing '-', TLD letters >= 2, <= 253.
- dateErr(v, {allowPast}): optional; YYYY-MM-DD, a real date, year <= 2100, not before today unless allowPast.
- textErr(v, what, min, max): trimmed length.
- safeHref(): http, https, mailto only, no credentials, no whitespace, <= 2048.
- safeInternalPath(): redirect after sign-in, only /app/ or /onboarding/, <= 300.
- CSV: .csv name <= 255, MIME in [text/csv, application/csv, application/vnd.ms-excel, text/plain, ''], 1 B to 1 MB, strict UTF-8, <= 1000 rows, header must start Name,Email. csvSafe() prefixes ' to cells starting = + - @ tab CR on export.

Mock data shapes (src/data/seed.ts)
- ReplyType: 'meeting' | 'pricing' | 'objection' | 'defer' | 'referral' | 'notinterested' | 'optout' | 'ooo' | 'unclear'
- Stage: 'new' | 'contacted' | 'meeting' | 'proposal' | 'negotiation' | 'won' | 'lost' (labels New, Contacted, Meeting scheduled, Proposal, Negotiation, Won, Lost)
- Currency: 'USD' | 'PKR'
- Company {id, name, domain, industry, size ('201–500' style text, includes '501–1000' and '1001+'), location, owner (name string), website}
- Contact {id, name, email, title, companyId|null, phone, status 'Active'|'Opted out'|'Suspended', tint, last (text like '2 min ago'), location, owner (name string)}
- Deal {id, name, companyId|null, contactId|null, amount (number), currency, stage, owner (name string), close ('YYYY-MM-DD'), waiting?, lostReason?, note?, created (text)}
- Thread {id, contactId, subject, preview, time, status 'waiting'|'done'|'none', replyType, confidence 0-100, dealId|null, mailbox (email), messages [{from 'them'|'me', name, time, text}]}
- ReviewItem {id, contactId, dealId, subject, time, received, type, confidence 0-100, paragraphs [string], evidence (paragraph index), why (text), facts [[label, value]], actions [{id, label, on}], draft, usedFacts [fact names], status 'pending'|'approved'|'rejected'|'skipped'}
- Followup {id, contactId, title, sub, due (text), draft, done}
- CalEvent {id, day, date, time, dur, title, sub, contactId, kind 'meeting'|'hold'}
- Template {id, name, type ReplyType, uses (number), body, updated (text)}
- Fact {id, key, value, on, by (name), when (text)}
- Mailbox {id, email, provider 'Google'|'Microsoft', status 'ok'|'expired', sync (text), owner (name or 'Shared')}
- Member {id, name, initials, tint, email, role 'Owner'|'Admin'|'Member', team (one name), last (text), status 'Active'|'Invited'}
- AuditRow {id, time (text), who (name or 'Nudge'), action (human text), on (object text), tint, ini}
- weekBars [{d, a approved, p pending}] x7, typeMix [{t ReplyType, n}]
- Settings (client only): theme, mode 'draft'|'auto', approvals (32), threshold (85, clamped 60-99), quietOn, quietFrom/quietTo ('8:00 PM' text), tz ('Asia/Karachi'), notif {review, followup, meeting, digest, mailbox}, ints {google, microsoft, calendar, slack, hubspot, webhooks}, twoFA, dealStages (string list)

Hardcoded values to replace with server data: the name 'Mahad Baig' / 'Mahad' / 'MB' / 'mahad@acme.co' (Home greeting, Shell account menu, Profile, Security, Notifications, audit 'who', new record owner), 'Acme Sales' (workspace switcher, Workspace name), bell badge '3' and its three texts, Home '+2 vs yesterday' and '8 +' approved today, Home sparklines, Reports accuracy series and per-type accuracy, Calendar header 'Asia/Karachi · Quiet hours 8 PM to 8 AM', Review empty state quiet hours text, Security sessions list, Profile phone '300 5550142'.

Demo-only items visible in real mode too: Sign-in text 'Demo workspace mahad@acme.com · Nudge2026' (the mock user is mahad@acme.co, the mock accepts any password of 6+ characters), Verify 'Demo code 246810' button, Review 'Reset demo data' button. Landing 'See the demo workspace' calls startDemo(), which returns null in real mode, then the guard redirects to sign-in.

## 1. Public routes

### / (Landing)
Static marketing page. Actions: Sign in, Start free (/sign-up), See the demo workspace (mock only). No data.

### /foundations
Static design-system page. No data.

### /sign-in
Shows: Google, Microsoft 365, SSO buttons; email + password form; 'Keep me signed in for 30 days' (default on); notice 'Your session ended' when routed with state.notice = 'expired'.
Fields:
- Work email: emailErr(); normEmail on blur; maxLength 254; autocomplete username.
- Password: required, <= 128, no composition rules; maxLength 128; autocomplete current-password.
Actions: submit -> api.auth.login; on success hydrate workspace and go to safeInternalPath(state.from) or /app/home. 'Forgot password?' -> /reset.
Errors: any login failure shows 'That email and password do not match.'; 429 locks the form (UI lock 30 s); 5 failures in the UI also lock 30 s (hint only).

### /sign-up
Shows: provider buttons; Individual / Business team toggle (default Business); time zone read from the browser (shown, a 'Change' link that does nothing; NOT sent to the API).
Fields:
- Full name: personErr() (2-80, a letter, no < >); maxLength 80.
- Company (Business only): nameErr(co, 'company name', 2, 120); maxLength 120.
- Work email: emailErr(); normEmail.
- Password: passwordErr(pw, {email, name}); strength meter pwScore.
Actions: submit -> api.auth.register({name, company?, email, password, type}) then /verify with state.email. Provider buttons in mock mode go to /onboarding/1.

### /verify
Requires state.email (valid email) else redirect to /sign-up. Email is never in the URL.
Fields: 6 single-digit boxes; paste keeps digits only, max 6; must be exactly 6 digits.
Actions: Verify -> api.auth.verifyEmail({email, code}) -> hydrate -> /onboarding/1. Resend after a 42 s countdown -> api.auth.resendCode(email). UI lock after 5 wrong codes until resend. Text says the code expires in 10 minutes.

### /reset
Field: Work email (emailErr). Action: api.auth.requestReset(email). Always shows 'If an account exists for <email>, a link is on its way. It works once and expires in an hour.' Mock shows a demo link.

### /new-password
Token from ?token= (read once, removed from the address bar) or router state; must match /^[\w-]{4,200}$/, else 'This link is not valid'.
Fields: New password (passwordErr with email from state if present), Confirm (must match).
Action: api.auth.resetPassword({token, password}) -> toast -> /sign-in. Text says other devices are signed out.

### /onboarding/:step (1-5, requires sign-in)
1 Connect mailbox: pick Google or Microsoft (local state only; nothing connects). Must pick one or 'Skip for now'.
2 Approved facts: list with on/off toggles; add fact (name: nameErr 2-60, unique ignoring case; value: textErr 5-200). Must have at least one fact on.
3 Mode: Draft-only (selectable), 'Act when sure' locked until 50 approvals; confidence bar slider 60-99.
4 Hours: time zone select (4 fixed zones: Asia/Karachi, Europe/London, America/New_York, Asia/Dubai); quiet hours toggle; From (6-10 PM), To (6-9 AM) as text options.
5 Sample reply preview (static). 'Go to Nudge' -> /app/home.
All choices are written to the client store only. 'Skip setup' -> /app/home.

## 2. App shell (/app/*)

Top bar: workspace switcher (one hardcoded workspace, 'New workspace' not available), search button (Ctrl K), Draft-only pill (shows settings.mode, links to automation), help popover, notifications bell (hardcoded list), theme toggle, account menu (name, email, Settings, Sign out -> api.auth.logout then clear store).
Sidebar counts: pending reviews, open follow-ups.
Command palette: searches pages, contacts (name + email) and deals (name + amount) in memory; max 100 chars; 12 results.
New email modal (from sidebar and Inbox):
- From: select of mailboxes with status ok.
- To: emailErr(); refused if the address matches a contact (case-insensitive) whose status is Opted out or Suspended.
- Subject: textErr 2-200, must be one line.
- Message: textErr 5-5000, control characters stripped as typed.
- Action 'Send for approval': toast and audit row only. Nothing is stored as a draft.
Ask Nudge drawer: see /app/agent.

## 3. App routes

### /app/home
Shows: greeting, pending review count, approved today, open pipeline (USD only sum + count), approvals toward 50, 'Waiting for you' list (contact, company, evidence sentence, reply type, confidence, age), last 7 days bars (approved vs pending), reply type mix with percentages, today's events (first 3), pipeline by stage (USD only) and a separate PKR total line.
Actions: Start review, open review, links to calendar and pipeline. No forms.

### /app/review
Shows: list of review items (contact, age, evidence sentence, type, confidence or status); selected email (contact, company, email, received time, linked deal chip with amount, subject, paragraphs with the evidence paragraph highlighted); side panel: suggested type (select of 9), confidence vs the bar, why text, extracted facts (label/value pairs), 'When you approve, Nudge also will' action checkboxes, draft textarea, 'Used <facts>' tag, word count, 'From mahad@acme.co'.
Actions and rules:
- Change type (select of 9 reply types).
- Toggle each suggested action.
- Edit draft: control characters stripped; maxLength 5050.
- Approve (A): only if pending; contact status must be Active; draft not empty and <= 5000. Runs actions (move deal stage, set follow-up, add contact), marks thread done, approvals + 1, audit row, toast with Undo (toast text says 'Undo within 7 days').
- Reject (R): reason required from [Wrong tone, Wrong facts, Wrong reply type, Too long, Should not reply, Other]; optional note <= 1000.
- Skip (S). Keyboard J/K to move.
- Empty state: 'All caught up', approved-this-session list, 'Reset demo data'.

### /app/inbox
Shows: mailbox filter (mailboxes with status ok), tabs All / Waiting / Replied with counts, thread rows (contact, company, time, subject, preview, reply type, status), thread view (subject, contact link, company, email, mailbox, Nudge summary = preview, type, confidence, Open deal, 'Review draft' when waiting), messages (sender, time, text split into paragraphs).
Actions: select thread, New email, Review draft -> /app/review. No forms.

### /app/follow-ups
Shows: cards (contact, title, sub, due text, Queued tag when done).
Actions: Review draft (expand), edit draft (textErr 5-5000), Approve & queue (sendFollowup: 1-5000 chars, marks done), Snooze a day (toast only).

### /app/calendar
Shows: events grouped by day (time, duration, title, sub); holds shown amber with 'Confirm hold' (toast only). 'Open in Google' (toast only).

### /app/agent (and the Ask Nudge drawer)
Chat with canned answers computed from the store (pipeline, reviews, follow-ups, calendar). Input <= 500 chars; Agent mode toggle; 'Needs your OK' buttons (toast only). Nothing stored.

### /app/pipeline
Shows: open deal count and USD total (plus PKR total when present), owner filter (members), currency filter (All/USD/PKR), tabs Open / Won / Lost with counts. Open: board of the first 5 stages with per-stage count and separate USD and PKR sums, deal cards (name, company or contact name, amount, owner first name, close MM-DD, 'Reply waiting for you'). Won/Lost: table (deal, company, owner, amount, close date or lost reason).
Actions:
- Drag a card to another stage (moveDeal). Drop on 'lost' opens the Lost modal (the board only shows 5 open stages, so this path is not reachable from the board).
- Add deal modal:
  - Deal name: nameErr 2-80.
  - Company: optional select.
  - Contact: optional select, filtered to the chosen company.
  - Amount: amountErr (required, > 0, 2 decimals, < 1e12).
  - Currency: USD or PKR.
  - Stage: one of the first 5 stages.
  - Owner: must be a member name.
  - Expected close: optional; dateErr (not in the past, <= 2100). If empty the store sets '2027-03-31'.
- Lost modal: reason required from [Chose another vendor, Budget, No decision, Bad timing, Not a fit].

### /app/pipeline/:id
Shows: name, company, contact link, owner, amount, stage track (5 open stages, clickable), Won/Lost tag with reason, details (stage, currency, expected close, created, reply waiting), notes textarea, activity timeline (messages of linked threads + 'Deal created').
Actions: Edit modal (name nameErr 2-80; amount amountErr; expected close dateErr allowPast; currency not editable), Mark won, Mark lost (Lost modal), click a stage to move, Save note (cleanMulti, <= 1000), Open in Inbox.
No concurrency check in the UI.

### /app/contacts
Shows: total count, search (name + email + company, <= 100), status filter (All, Active, Opted out, Suspended), owner filter (4 hardcoded names), table (name, email, company, title, owner, status, last contact), count shown.
Actions:
- Add contact modal:
  - Full name: personErr 2-80.
  - Email: emailErr, unique among contacts ignoring case. Required.
  - Title: optional, <= 80 after clean.
  - Phone: optional, phoneErr.
  - Company: optional select.
  - Owner is always 'Mahad Baig'; location empty.
- Import CSV modal: file rules in section 0; columns Name, Email, Title; per row: name must not start with a formula character, personErr, emailOk, title <= 80, no duplicate (existing or within file); shows first 8 rows with verdicts; imports valid rows with company none.
- Export CSV of the filtered list (Name, Email, Company, Title, Status), formula-safe.
- Download template CSV.

### /app/contacts/:id
Shows: name, title, company link, opted-out callout, profile (email, phone, location, owner, status, last contact), deals (name, stage, amount), conversations (subject, preview).
Actions: Mark opted out / Remove opt-out (toggles status, audit row).

### /app/companies
Shows: count, search (name + industry + location), table (name, domain, industry, location, people count, open deal count, open value USD only).
Actions: Add company modal:
- Company name: nameErr 2-120, unique ignoring case.
- Domain: optional, domainErr.
- Industry: optional, <= 80.
- Stored with industry 'Other' if blank, size '–', location '–', website = domain, owner 'Mahad Baig'.

### /app/companies/:id
Shows: about (website, industry, size, location, owner), people (name, title, status), deals (name, stage, amount), a hardcoded suggested person (Omar Siddiqui, company c3 only).
Actions: Add person (Add contact modal with company preset), Add suggested person.

### /app/templates
Shows: template list (name, type, uses), editor (name, reply type, body), variable chips {first_name} {company} {day} {time} {date} {sender_first_name}, approved facts (on only) that insert {fact_key}.
Actions:
- New template: name nameErr 2-80, unique ignoring case; reply type; body starts as a fixed greeting.
- Edit name (same rules), type, body (textErr 5-5000). Edits apply live; Save only shows a toast.
- Delete (no confirmation).

### /app/reports
Shows: range 7/30/90 days; replies handled, approved without edits (81%), type accuracy, total approvals; accuracy line chart vs the bar; accuracy by reply type; pipeline by stage (USD only). All numbers are hardcoded except deals, approvals and threshold.
Actions: Export CSV (reply type, replies, accuracy %).

### /app/settings/:tab (unknown tab -> profile)
profile
- Full name: personErr. Email read-only. Phone: country code select (+92, +1, +44, +971; not saved) + number (phoneErr). Time zone: 4 fixed zones.
- Save: writes only settings.tz in the store. Appearance: light/dark/system (localStorage).
security
- Change password: current required (<= 128); new passwordErr with the hardcoded email and name, and must differ from current; confirm must match. Calls api.auth.changePassword. Show passwords checkbox.
- Two-step sign-in toggle (store only).
- Active sessions list (hardcoded) with Sign out per other session.
workspace
- Workspace name: nameErr 2-120. Default currency: USD/PKR (not saved). Time zone: 3 zones. Save: toast only.
- Quiet hours: toggle, From, To (text options), saved to the store immediately.
- Deal stages: list; last two (Won, Lost) fixed; others renamable; first stage cannot move; add stage (<= 12 stages, inserted before Won); each name 1-40 after clean, no < >, unique ignoring case. Save writes settings.dealStages only (deals still use the 7 fixed ids).
team
- People: name, email, role (Owner fixed; Admin/Member select), team, last active, Remove (non-owners). Role change writes an audit row; remove does not.
- Teams card: Sales and Support with hardcoded descriptions and member avatars. No team CRUD.
- Invite modal: email (emailErr, not already a member ignoring case), role Member or Admin. Creates an 'Invited' member with a name made from the email.
mailboxes
- List: provider logo, email, provider, owner, sync text; expired shows 'Sign in again' (sets ok), else Disconnect (removes it). Connect modal adds a fake mailbox.
automation
- Mode: Draft-only / Act when sure (locked until approvals >= 50). Confidence bar slider 60-99. By reply type: 'Always ask me' toggle per type; Opt-out and Unclear forced on. Toggles are local component state (lost on navigation).
facts
- List (name, value, updated text, by), Edit, on/off toggle (audit row).
- Add/Edit modal: name nameErr 2-60, unique ignoring case; value textErr 5-200 with a counter.
notifications
- Toggles: review, followup, meeting, mailbox, digest. 'Sent to mahad@acme.co'.
integrations
- Cards: Google Workspace, Microsoft 365, Calendar, Slack, HubSpot, Webhooks with Connect/Disconnect (store only).
audit
- Filter Everyone / People / Nudge; Export CSV (When, Who, Action, On); rows (time, who, action, on).

### * (NotFound)
Static. Unknown ids on detail routes show 'not found' inside the page.

## 4. Tests in the frontend repo
- tests/unit/validate.test.ts: email, names, password, amount, phone, domain, date, CSV, safeHref, safeInternalPath, idOk.
- tests/unit/api.test.ts: client headers (credentials, CSRF only on unsafe methods, no-store, no redirects), 401/403/429/400/5xx mapping, timeout, path guard, token in memory, mock auth rules (same message for wrong email or password, 5-try 429, single-use code and reset link).
- tests/e2e/*.spec.ts (Playwright, against vite preview): auth forms, CSV import/export, form rules, route guards, CSP and headers, XSS rendering.
None of them call a real backend.
