# Gap report

List only. Nothing here changes the schema. Sources:
- Frontend: D:\Desktop\Nudge-frontend (src/, SECURITY.md).
- SQL: nudge_schema_v3_1.sql.
- Design: nudge_db_design_v3_1.md. Its section 12 already lists proposals H3, H4, M9, M10, M12, M13 and L13-L17; they are cited where they match.
- nudge_validation_spec_v3_1.md was not found, so section 3 compares validate.ts and SECURITY.md with the SQL CHECKs and the design doc only.

## 1. Frontend shows or does something with no table or column

| ID | Frontend | Missing in schema | Note |
|---|---|---|---|
| G-A1 | Sign-up shows the browser time zone | Nothing missing, but the register call does not send it, and users.timezone and organizations.timezone are NOT NULL with no default | Frontend change only |
| G-A2 | Workspace 'Default currency' (USD/PKR) | organizations has no currency column | deals.currency is NOT NULL with no default (P1 removed 'PKR') |
| G-A3 | Contact status 'Suspended' | contacts has only opted_out_at | The frontend blocks sends to Suspended contacts |
| G-A3 | Contact 'location' | No column | |
| G-A3 | Contact 'last contact' | No column | Derivable from max(email_threads.last_message_at) per contact, later |
| G-A3 | Company 'location' | No column | |
| G-A3 | Company 'website' | No column (only domain) | |
| G-A4 | Deal 'Notes' box (save one note) | No deals.note | activities type 1 Note exists but is an FYP-II table and is a timeline, not one field |
| G-A5 | Google / Microsoft 365 / SSO sign-in buttons | No table for a provider subject id or linked identities | Design L13-L17: django-allauth would add tables |
| G-A6 | New email (compose) and follow-up drafts 'Approve & queue' | reply_drafts.message_id is NOT NULL; no email_account_id, contact_id, follow_up_id or subject on reply_drafts | Design H4 |
| G-A7 | Review: suggested action checkboxes (move stage, set follow-up, add contact) | No table | Design H3 (suggested_actions) |
| G-A7 | Review: reject reason and note | No column | Design H3 |
| G-A7 | Review: skip | No status code; reply_drafts.status has 1 Draft, 2 Approved, 3 Sent, 4 Failed, 5 Discarded | Design H3 |
| G-A7 | Review: 'why' explanation | No column | |
| G-A7 | Review: the evidence sentence for the reply type | extractions hold evidence for extracted fields, not for the label decision; predictions have no evidence column | |
| G-A7 | Review: 'Used <facts>' | No link between reply_drafts and company_facts | |
| G-A8 | Approved fact | company_facts.kind is NOT NULL (1 Pricing, 2 Product, 3 Policy, 4 Other); the frontend has no kind | Not a missing column; a missing UI field (or a fixed default) |
| G-A9 | Global mode 'Draft-only' / 'Act when sure' | No organizations column | Design M9 |
| G-A9 | Global confidence bar (one number, 60-99, default 85) | category_settings.min_score is per label (default 0.900) | Design M9 |
| G-A9 | Two-step sign-in toggle | No TOTP secret or 2FA flag on users | |
| G-A10 | Notification toggles per event (review, follow-up, meeting, mailbox, digest) | notification_channels is per channel (email, Slack, ...), not per event | Design L13-L17 mentions digest time |
| G-A11 | Calendar 'hold' events and 'Confirm hold' | meetings.status has no hold | Design M12. meetings is a pending table |
| G-A12 | Integrations: Calendar, Webhooks | No table | Design M13 |
| G-A12 | Integrations: Slack | Only a notification_channels row (channel 2), not a workspace integration | Design M13 |
| G-A13 | Session location 'Karachi, PK' | user_sessions has ip_address only | Design L13: GeoIP at display time |
| G-A14 | Team description ('Replies and deals for new business') | teams has name only | |
| G-A15 | Onboarding progress (which step is done) | No column | The frontend does not keep it either |
| G-A16 | Review / thread status 'waiting for you' | email_threads.status 2 means waiting on them | Different meaning. 'Waiting for you' must be derived from reply_drafts status 1 |
| G-A17 | Inbox type and confidence per thread | Not on email_threads | Derivable from predictions of the latest inbound message. Design M10 |
| G-A18 | 'Approvals to unlock Act when sure' (50) | No counter column | Derivable: count of reply_drafts with approved_by_id. The threshold 50 is a rule with no home (M9) |
| G-A19 | Agent chat history | assistant_* tables exist (FYP-II); the frontend keeps nothing | Not a gap, a later item |
| G-A20 | Undo approval 'within 7 days' (toast text) | Undo window is send_after, a 10-minute hold per design (REQ-SF-03) | The value conflicts. See section 3 |

## 2. Tables with no screen

No screen at all:
- lead_forms, lead_submissions
- mailbox_access
- label_sets, ml_models, evaluation_runs, dataset_items, dataset_labels (internal and research)
- notification_channels (the Notifications tab is per event, not per channel), call_logs
- email_chunks
- crm_stage_mappings, external_links
- prospect_calls, sequences, sequence_steps, sequence_enrollments
- invitations: there is an invite modal, but no pending list, resend, cancel or accept page

Used only indirectly (a screen shows data that would come from it, with no screen of its own):
| Table | Where it would surface |
|---|---|
| user_sessions | Security tab sessions (hardcoded today) |
| teams, team_members | Team tab 'Teams' card is read-only and hardcoded; Member.team is one string, the schema is many-to-many |
| activities | Deal 'Activity' timeline (built from threads today) |
| message_recipients | Inbox (not shown) |
| labels | The 9 reply types (codes differ, section 3) |
| predictions, prediction_labels, extractions | Review and Inbox type, confidence, facts |
| corrections | Review type change and reject (not stored) |
| category_settings | Automation 'By reply type' |
| reply_drafts | Review |
| follow_ups | Follow-ups |
| notifications | Bell (hardcoded) |
| email_templates, company_facts | Templates, Approved facts |
| assistant_conversations, assistant_messages, assistant_citations | Agent (not stored) |
| crm_connections | Integrations HubSpot card |
| meetings | Calendar |
| audit_logs | Audit tab |

## 3. Mismatches: validate.ts / frontend vs SQL / design

Update 2 Nov 2026: cross-checked against docs/nudge_validation_spec_v3_1.md.
- The rows below are unchanged.
- Spec differences and the rule we enforce are in BACKEND_PLAN section 6, 'Differences from the validation spec'.
- New mismatches found through the spec:
| Field | Frontend | Spec | SQL | Note |
|---|---|---|---|---|
| sign-up account type | type 'Individual' or 'Business'; company only for Business; Individual sends no company key | Business needs a company name; Individual uses the user's name | organizations.account_type 1/2, name NOT NULL | Matches. API_CONTRACT register now documents the exact body |
| users.full_name | 2-80 | 2-150 | varchar(150) | Frontend limit wins (Q-30) |
| users.email on sign-up | same message for every address | 'already in use' (SRS) | unique | We keep the same answer (BACKEND_PLAN 9, point 8) |
| control characters | stripped silently | rejected | n/a | Server now rejects |
| company domain | host only, URL refused | URL accepted, host kept | varchar(253), lower-case | We keep refusing URLs |
| contact email | required | optional | nullable | Q-14 |
| contact job_title | <= 80 | <= 100 | varchar(100) | Q-30 |
| stage name | <= 40 | <= 60 | varchar(60) | Q-30 |
| deal title | 2-80 | <= 150; duplicates only warn | varchar(150) | Q-30; warning shape pending |
| deal amount | required, > 0, 2 decimals | optional, >= 0, decimals per currency | numeric(18,2) NULL, >= 0 | Q-18 + ISO minor units |
| expected close date | not past on create | past allowed | date | Q-18 |
| PKR decimals | n/a | 0 | n/a | Spec error: ISO 4217 gives PKR 2 |
| person-name, company-name rules | defined in validate.ts | referenced, never defined | n/a | Gap in the spec |
| teams, team_members | read-only, hardcoded card | Midterm tables | present | GET /teams/ is midterm; CRUD later |

Lengths
| Field | Frontend | SQL | Note |
|---|---|---|---|
| G-C1 user full name | 2-80 | users.full_name varchar(150) | |
| G-C1 contact name | one field, 2-80 | first_name varchar(80) NOT NULL, last_name varchar(80) NULL | Split name vs single name |
| company name | 2-120 | companies.name varchar(150) | |
| workspace name | 2-120 | organizations.name varchar(150) | |
| contact title | <= 80 | contacts.job_title varchar(100) | |
| industry | <= 80 | companies.industry varchar(80) | Match |
| deal name | 2-80 | deals.title varchar(150) | |
| stage name | 1-40 | deal_stages.name varchar(60) | |
| lost reason | one of 5 fixed texts | deals.lost_reason varchar(200) free text | |
| fact name | 2-60 | company_facts.title varchar(150) | |
| fact text | 5-200 | company_facts.body text | |
| template name | 2-80 | email_templates.name varchar(100) | |
| template body | 5-5000 | email_templates.body text | |
| subject | 2-200 | email_messages.subject text, email_templates.subject text | |
| draft / message body | 1-5000 (approve), 5-5000 (compose, follow-up) | reply_drafts.body text | Two different minimums in the frontend |
| deal note | <= 1000 | no column | |
| team name | not editable | teams.name varchar(80) | |
| email | 254, local part 64, ASCII only | varchar(254), CHECK lower-case | Match. Non-ASCII emails refused by the frontend (SECURITY.md) |
| domain | 253 | varchar(253), CHECK lower-case | Match |
| password | 8-128 raw | users.password varchar(128) holds the hash | Not a conflict: an Argon2 hash is about 100 characters |

Formats
| Field | Frontend | SQL | Note |
|---|---|---|---|
| phone | optional '+', 7-15 digits, spaces, brackets and dashes allowed | CHECK '^\+[1-9][0-9]{7,14}$' (E.164, '+' required, 8-15 digits, first digit not 0) | A 7-digit number or one without '+' passes the UI and fails the DB |
| phone (contacts) | same | same CHECK | The design doc says contacts.phone is 'free format from CSV/forms', which contradicts the CHECK |
| profile phone country code | select of +92, +1, +44, +971, not saved | n/a | Not global |
| currency | 'USD' or 'PKR' | CHECK '^[A-Z]{3}$' | Any 3 letters pass the DB; the UI allows 2 |
| amount | required, > 0, < 1e12, 2 decimals | numeric(18,2) NULL, CHECK amount >= 0 | UI forbids 0 and null; DB allows both and up to about 1e16 |
| expected close | YYYY-MM-DD, <= 2100, not past on create | date NULL | Year limit and 'not past' are UI rules only. The UI also fills '2027-03-31' when empty |
| time zone | fixed lists of 3 or 4 zones | varchar(64) | Not global |
| quiet hours | '8:00 PM' text options, on the Workspace tab (organization) | users.quiet_hours_start/end time, per user | Level differs: organization in the UI, user in the DB |
| confidence | integer 0-100, bar 60-99, default 85 | predictions.decision_score numeric(4,3) 0-1; category_settings.min_score numeric(4,3) default 0.900 | Scale (x100) and default (85 vs 90) differ |
| money totals | USD only on Companies, Home pipeline and Reports | grouped by currency (design rule) | The frontend drops non-USD from those totals |

Allowed values
| Field | Frontend | SQL | Note |
|---|---|---|---|
| roles | Owner, Admin, Member (invite: Member or Admin) | 1 Owner, 2 Admin, 3 Manager, 4 Member | Manager missing in UI |
| member status | Active, Invited | memberships 1 Active, 2 Suspended, 3 Removed; 'Invited' = invitations row | |
| contact status | Active, Opted out, Suspended | opted_out_at only | |
| company size | free text: '11–50', '51–200', '201–500', '501–1000', '1001+' | size_range 1 1-10, 2 11-50, 3 51-200, 4 201-500, 5 500+ | '501–1000' and '1001+' do not map; 5 is '500+' |
| deal stage | 7 fixed slugs: new, contacted, meeting, proposal, negotiation, won, lost | deal_stages rows (uuid) with outcome 1 Open, 2 Won, 3 Lost | Editable stages in Settings are never used by deals |
| stage rules | Won and Lost fixed last; first stage fixed first; at most 12 | none in SQL | Service rules only |
| reply type codes | meeting, pricing, objection, defer, referral, notinterested, optout, ooo, unclear | labels: meeting_request, pricing_request, objection, defer, referral, not_interested, opt_out, out_of_office, unclear, other | 5 codes differ; 'other' has no UI |
| reply type label | 'Pricing question' (seed), 'Pricing request' (onboarding) | 'Pricing request' | |
| mailbox provider | Google, Microsoft | 1 Gmail, 2 IMAP/SMTP, 3 Outlook (FYP-II) | IMAP has no UI; Outlook is FYP-II |
| mailbox status | ok, expired | 1 Active, 2 Error, 3 Disconnected | Disconnect in UI deletes the row; design keeps it with status 3 |
| review status | pending, approved, rejected, skipped | reply_drafts 1 Draft, 2 Approved/queued, 3 Sent, 4 Failed, 5 Discarded/undone | No 'skipped', no 'sent' or 'failed' in UI |
| thread status | waiting (for you), done (replied), none (no reply needed) | 1 Open, 2 Waiting on them, 3 Closed | Different meaning |
| follow-up | done boolean, due text | type 1-4, status 1 Open, 2 Snoozed, 3 Done, 4 Cancelled, due_at, close_reason | |
| integrations | google, microsoft, calendar, slack, hubspot, webhooks | crm_connections 1 HubSpot, 2 Generic | |
| visibility | none in UI (everyone sees everything) | 1 Private (default), 2 Team, 3 Organization | With the DB default, a Member's new records are hidden from other Members |
| audit action | free text ('Approved reply') | CHECK '^[a-z_]+\.[a-z_]+$' | Server must map codes to text |

Uniqueness
| Field | Frontend | SQL | Note |
|---|---|---|---|
| G-C3 company | name unique ignoring case | domain unique per organization among live rows; name only indexed | Each side checks a different field |
| contact | email unique ignoring case, email required | (organization_id, email) unique among live rows; email nullable | Match on uniqueness (DB stores lower-case); required differs |
| stage, template, fact names | unique ignoring case | stages: unique lower(name) per organization; templates and facts: no unique rule | Templates and facts uniqueness are service rules only |
| team name | n/a | unique lower(name) per organization | |

Rules that disagree between the frontend and the design doc
| Topic | Frontend | Design doc |
|---|---|---|
| Email verification | 6-digit code, 10 min, resend after 42 s | Section 2 'users': signed links, no token table. Section 12 M1: code in Redis, 10 min, resend 30 s |
| Undo after approve | 'Undo within 7 days' | send_after undo hold of 10 minutes (REQ-SF-03, P20) |
| Unlock automation | after 50 approvals, one global switch | design landing text: per reply type, after 50 approved reviews; category_settings per label |
| Who sees the audit log | every member | not stated |
| Migrations | (user decision) unmanaged models, SQL file is the source of truth | Section 12: 'Django migrations own the tables; this SQL file is the reference' |
| Money precision | n/a | Section 0.2 says numeric(12,2); P10 and the SQL use numeric(18,2) |

Other findings
- Sign-in hint shows 'mahad@acme.com' while the mock user is 'mahad@acme.co'.
- Demo texts render in real mode as well: sign-in demo credentials, verify demo code, 'Reset demo data'.
- Client maps every 401 to 'session ended' and redirects. A wrong password on /auth/login/ would show the expired-session screen, not 'That email and password do not match.' The same applies to verify (400 -> generic 'Check the highlighted fields').
- Client has no refresh step. After a reload the access token is gone, and /auth/me/ with no token returns 401 -> signed out.
- Client does not send X-Organization-ID.
- Login, register and reset need CSRF, but nothing calls GET /auth/csrf/ first.
