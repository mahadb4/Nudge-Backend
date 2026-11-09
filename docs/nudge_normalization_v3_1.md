# Nudge database v3.1: normalization analysis (1NF, 2NF, 3NF, BCNF)

## 1. Method and honesty about its limits

A normal form is a statement about functional dependencies, and dependencies come from business rules, not from the data. So this analysis uses:
- the primary and candidate keys read from the live PostgreSQL catalog,
- every composite foreign key read from the catalog (they are where copies of a parent's value appear in a child),
- the column purposes in the ERD and the rules in the SRS to find derived or cached values.
It is a design review of all 50 tables, not an automatic mathematical proof. A dependency that nobody wrote down in the ERD, the SRS or a constraint would not appear here.

## 2. Result in one paragraph

All 50 tables are in 1NF, with 7 deliberate jsonb columns listed in section 3. Every table has a single-column surrogate primary key (uuid), so no non-key column can depend on only part of the primary key. Against the other natural candidate keys, the only partial or transitive dependencies are the 54 copies of the parent's organization_id and the few other copies listed in section 4. 22 tables have no exception at all (3NF and BCNF). 28 tables carry one or more documented exceptions.
The exceptions are deliberate. The usual danger of a denormalized copy is that it can disagree with the original. Here a composite foreign key makes the database check the copy against the parent, so the two can never disagree. That is why the copies are safe, and why they are the way Nudge keeps one organization's data from linking to another's.

## 3. First normal form: atomic values

Every column holds one value of one type. No column stores a comma-separated list or a repeating group. The following columns hold structured data, and they are an intentional exception to strict 1NF because the application never filters or joins on the inside of them; each is written once and read whole:

| Column | Why it is jsonb |
|---|---|
| audit_logs.details | before/after values; written once, read as a whole |
| email_messages.headers | raw headers kept for debugging; read as a whole |
| evaluation_runs.confusion_matrix | a matrix of results; read as a whole |
| evaluation_runs.per_class | per-class metrics; read as a whole |
| lead_forms.fields | the form definition; read and edited as a whole |
| lead_submissions.payload | answers exactly as submitted; read as a whole |
| ml_models.config | model settings; read as a whole |

email_chunks.embedding is a vector of 384 numbers. The embedding model treats it as one value, so it is atomic for this purpose.

## 4. Second and third normal form: the documented exceptions

### 4.1 Tenant copies (organization_id on child tables)

54 composite foreign keys have the form (organization_id, parent_id) referencing parent(organization_id, id). In the parent, id determines organization_id, so in the child the column parent_id determines organization_id. Strictly this is a transitive dependency. It is kept on purpose: it is what lets the database reject a link between two organizations (SRS NFR-SEC-03), and the foreign key guarantees the copy is always correct.

| Child table | Foreign-key column that determines organization_id | Parent |
|---|---|---|
| team_members | team_id | teams |
| team_members | membership_id | memberships |
| invitations | team_id | teams |
| companies | team_id | teams |
| contacts | company_id | companies |
| contacts | team_id | teams |
| deals | company_id | companies |
| deals | primary_contact_id | contacts |
| deals | stage_id | deal_stages |
| deals | team_id | teams |
| activities | contact_id | contacts |
| activities | deal_id | deals |
| activities | message_id | email_messages |
| lead_forms | team_id | teams |
| lead_submissions | form_id | lead_forms |
| lead_submissions | contact_id | contacts |
| email_accounts | team_id | teams |
| mailbox_access | email_account_id | email_accounts |
| email_threads | email_account_id | email_accounts |
| email_threads | contact_id | contacts |
| email_threads | deal_id | deals |
| email_messages | email_account_id | email_accounts |
| predictions | message_id | email_messages |
| extractions | message_id | email_messages |
| extractions | prediction_id | predictions |
| corrections | prediction_id | predictions |
| corrections | extraction_id | extractions |
| email_templates | team_id | teams |
| reply_drafts | message_id | email_messages |
| reply_drafts | prediction_id | predictions |
| reply_drafts | template_id | email_templates |
| reply_drafts | sent_message_id | email_messages |
| follow_ups | thread_id | email_threads |
| follow_ups | deal_id | deals |
| follow_ups | source_extraction_id | extractions |
| notifications | follow_up_id | follow_ups |
| call_logs | notification_id | notifications |
| email_chunks | email_account_id | email_accounts |
| crm_stage_mappings | connection_id | crm_connections |
| crm_stage_mappings | deal_stage_id | deal_stages |
| external_links | connection_id | crm_connections |
| external_links | contact_id | contacts |
| external_links | deal_id | deals |
| external_links | activity_id | activities |
| meetings | deal_id | deals |
| meetings | contact_id | contacts |
| prospect_calls | meeting_id | meetings |
| prospect_calls | contact_id | contacts |
| prospect_calls | deal_id | deals |
| sequence_steps | sequence_id | sequences |
| sequence_steps | template_id | email_templates |
| sequence_enrollments | sequence_id | sequences |
| sequence_enrollments | contact_id | contacts |
| sequence_enrollments | email_account_id | email_accounts |

The database has 77 composite foreign keys in total. 54 of them are the pattern above. The other 19 tenant keys point to (organization_id, user_id) in memberships (or similar), where the user does not determine the organization, so they create no dependency and are not listed. The remaining 4 are in 4.2.

### 4.2 Other copies guarded by composite foreign keys

| Child table | Copied column | Determined by | Parent | Why it is kept |
|---|---|---|---|---|
| email_messages | email_account_id | thread_id | email_threads | a message must be in the same mailbox as its thread |
| predictions | label_set_id | model_id | ml_models | a prediction must be for the task of its model; also needed by the one-final-prediction-per-task rule |
| notifications | user_id | channel_id | notification_channels | a notification can only use its recipient's own channel |
| email_chunks | email_account_id | message_id | email_messages | a chunk must be in the same mailbox as its message |

### 4.3 Derived or cached values

| Table | Column | What it is |
|---|---|---|
| email_threads | subject | copy of the first message subject (inbox list needs it without a join) |
| email_threads | last_message_at | equals the newest sent_at of its messages (inbox sort) |
| email_messages | snippet | first 200 characters of body_text (inbox list) |
| email_messages | search_tsv | generated by PostgreSQL from subject and body_text |
| deals | closed_at | set when the stage outcome becomes Won or Lost |
| prospect_calls | duration_sec | equals ended_at minus started_at (proposal L12: can be dropped) |
| predictions | is_final | marks the one prediction per message and task that the workflow uses |
| evaluation_runs | accuracy | result of scoring a model on a fixed split; stored on purpose as an immutable record |
| evaluation_runs | macro_f1 | same |
| evaluation_runs | coverage | same |

These are stored to make the screens fast (inbox list, search, pipeline) or to keep an immutable record (evaluation results). The service layer or PostgreSQL maintains each one. If the team prefers strict 3NF, they can be removed at the cost of a join or an aggregate on the hot screens; the benchmark in the test report shows the screens are fast with them.

## 5. Table-by-table result

Candidate keys listed are the unique rules other than the primary key (id). 'where' means the rule applies only to rows matching the condition (for example live, not soft-deleted, rows).

| Table | Columns | Other candidate keys | 1NF | 2NF | Result | Exceptions |
|---|---|---|---|---|---|---|
| organizations | 8 | - | 1NF | 2NF | 3NF/BCNF | - |
| users | 16 | (email) | 1NF | 2NF | 3NF/BCNF | - |
| user_sessions | 9 | (refresh_token_hash) | 1NF | 2NF | 3NF/BCNF | - |
| memberships | 7 | (organization_id, user_id) | 1NF | 2NF | 3NF/BCNF | - |
| teams | 5 | (organization_id, lower(name)) | 1NF | 2NF | 3NF/BCNF | - |
| team_members | 6 | (team_id, membership_id) | 1NF | 2NF | 3NF with documented exceptions | organization_id also determined by membership_id, team_id |
| invitations | 10 | (token_hash) | 1NF | 2NF | 3NF with documented exceptions | organization_id also determined by team_id |
| companies | 12 | (organization_id, domain) where (deleted_at IS NULL) AND (domain IS NOT NULL) | 1NF | 2NF | 3NF with documented exceptions | organization_id also determined by team_id |
| contacts | 16 | (organization_id, email) where (deleted_at IS NULL) AND (email IS NOT NULL) | 1NF | 2NF | 3NF with documented exceptions | organization_id also determined by company_id, team_id |
| deal_stages | 7 | (organization_id, lower(name)) | 1NF | 2NF | 3NF/BCNF | - |
| deals | 18 | - | 1NF | 2NF | 3NF with documented exceptions | organization_id also determined by company_id, primary_contact_id, stage_id, team_id; closed_at: set when the stage outcome becomes Won or Lost |
| activities | 9 | - | 1NF | 2NF | 3NF with documented exceptions | organization_id also determined by contact_id, deal_id, message_id |
| lead_forms | 9 | (public_key) | 1NF (jsonb noted) | 2NF | 3NF with documented exceptions | organization_id also determined by team_id; fields is jsonb (1NF exception): the form definition; read and edited as a whole |
| lead_submissions | 7 | - | 1NF (jsonb noted) | 2NF | 3NF with documented exceptions | organization_id also determined by contact_id, form_id; payload is jsonb (1NF exception): answers exactly as submitted; read as a whole |
| email_accounts | 15 | (organization_id, email_address) | 1NF | 2NF | 3NF with documented exceptions | organization_id also determined by team_id |
| mailbox_access | 6 | (email_account_id, user_id) | 1NF | 2NF | 3NF with documented exceptions | organization_id also determined by email_account_id |
| email_threads | 12 | (email_account_id, provider_thread_id) | 1NF | 2NF | 3NF with documented exceptions | organization_id also determined by contact_id, deal_id, email_account_id; subject: copy of the first message subject (inbox list needs it without a join); last_message_at: equals the newest sent_at of its messages (inbox sort) |
| email_messages | 19 | (email_account_id, provider_message_id) | 1NF (jsonb noted) | 2NF | 3NF with documented exceptions | organization_id also determined by email_account_id; email_account_id also determined by thread_id (via email_threads); snippet: first 200 characters of body_text (inbox list); search_tsv: generated by PostgreSQL from subject and body_text; headers is jsonb (1NF exception): raw headers kept for debugging; read as a whole |
| message_recipients | 5 | (message_id, type, email) | 1NF | 2NF | 3NF/BCNF | - |
| label_sets | 4 | (code) | 1NF | 2NF | 3NF/BCNF | - |
| labels | 6 | (label_set_id, code) | 1NF | 2NF | 3NF/BCNF | - |
| ml_models | 10 | (name, version); (label_set_id) where is_active | 1NF (jsonb noted) | 2NF | 3NF/BCNF | config is jsonb (1NF exception): model settings; read as a whole |
| evaluation_runs | 14 | - | 1NF (jsonb noted) | 2NF | 3NF with documented exceptions | accuracy: result of scoring a model on a fixed split; stored on purpose as an immutable record; macro_f1: same; coverage: same; confusion_matrix is jsonb (1NF exception): a matrix of results; read as a whole; per_class is jsonb (1NF exception): per-class metrics; read as a whole |
| predictions | 10 | (message_id, model_id); (message_id, label_set_id) where is_final | 1NF | 2NF | 3NF with documented exceptions | organization_id also determined by message_id; label_set_id also determined by model_id (via ml_models); is_final: marks the one prediction per message and task that the workflow uses |
| prediction_labels | 5 | (prediction_id, label_id); (prediction_id) where is_primary | 1NF | 2NF | 3NF/BCNF | - |
| extractions | 16 | - | 1NF | 2NF | 3NF with documented exceptions | organization_id also determined by message_id, prediction_id |
| corrections | 11 | - | 1NF | 2NF | 3NF with documented exceptions | organization_id also determined by extraction_id, prediction_id |
| dataset_items | 8 | (content_hash) | 1NF | 2NF | 3NF/BCNF | - |
| dataset_labels | 7 | (item_id, label_id, labeller_type, labelled_by_id, model_id) | 1NF | 2NF | 3NF/BCNF | - |
| category_settings | 11 | (organization_id, label_id) | 1NF | 2NF | 3NF/BCNF | - |
| email_templates | 11 | - | 1NF | 2NF | 3NF with documented exceptions | organization_id also determined by team_id |
| company_facts | 10 | - | 1NF | 2NF | 3NF/BCNF | - |
| reply_drafts | 19 | (idempotency_key); (sent_message_id) | 1NF | 2NF | 3NF with documented exceptions | organization_id also determined by message_id, prediction_id, sent_message_id, template_id |
| follow_ups | 16 | (thread_id, type) where (status = ANY (ARRAY[1, 2]) AND (thread_id IS NOT NULL) AND (type = ANY (ARRAY[1, 2])) | 1NF | 2NF | 3NF with documented exceptions | organization_id also determined by deal_id, source_extraction_id, thread_id |
| notification_channels | 9 | (user_id, channel, address) | 1NF | 2NF | 3NF/BCNF | - |
| notifications | 16 | (dedupe_key) | 1NF | 2NF | 3NF with documented exceptions | organization_id also determined by follow_up_id; user_id also determined by channel_id (via notification_channels) |
| call_logs | 11 | (notification_id); (provider_call_id) | 1NF | 2NF | 3NF with documented exceptions | organization_id also determined by notification_id |
| email_chunks | 8 | (message_id, chunk_index) | 1NF | 2NF | 3NF with documented exceptions | organization_id also determined by email_account_id; email_account_id also determined by message_id (via email_messages); embedding is a vector of 384 numbers (one atomic value to the model, not a repeating group) |
| assistant_conversations | 6 | - | 1NF | 2NF | 3NF/BCNF | - |
| assistant_messages | 7 | - | 1NF | 2NF | 3NF/BCNF | - |
| assistant_citations | 4 | - | 1NF | 2NF | 3NF/BCNF | - |
| crm_connections | 9 | (organization_id, provider) | 1NF | 2NF | 3NF/BCNF | - |
| crm_stage_mappings | 6 | (connection_id, deal_stage_id) | 1NF | 2NF | 3NF with documented exceptions | organization_id also determined by connection_id, deal_stage_id |
| external_links | 10 | (connection_id, contact_id) where (contact_id IS NOT NULL); (connection_id, deal_id) where (deal_id IS NOT NULL); (connection_id, activity_id) where (activity_id IS NOT NULL) | 1NF | 2NF | 3NF with documented exceptions | organization_id also determined by activity_id, connection_id, contact_id, deal_id |
| audit_logs | 10 | - | 1NF (jsonb noted) | 2NF | 3NF/BCNF | details is jsonb (1NF exception): before/after values; written once, read as a whole |
| meetings | 19 | (organization_id, calendar_provider, provider_event_id) where (provider_event_id IS NOT NULL) | 1NF | 2NF | 3NF with documented exceptions | organization_id also determined by contact_id, deal_id |
| prospect_calls | 19 | (provider_call_id) | 1NF | 2NF | 3NF with documented exceptions | organization_id also determined by contact_id, deal_id, meeting_id; duration_sec: equals ended_at minus started_at (proposal L12: can be dropped) |
| sequences | 7 | (organization_id, lower(name)) | 1NF | 2NF | 3NF/BCNF | - |
| sequence_steps | 7 | (sequence_id, "position") | 1NF | 2NF | 3NF with documented exceptions | organization_id also determined by sequence_id, template_id |
| sequence_enrollments | 10 | (sequence_id, contact_id) where (status = 1) | 1NF | 2NF | 3NF with documented exceptions | organization_id also determined by contact_id, email_account_id, sequence_id |

## 6. Short answer for the viva

Nudge is normalized to third normal form. Every table has a surrogate primary key and a natural unique key, lookups such as stages, labels and models are their own tables, and many-to-many links use junction tables (team_members, mailbox_access, prediction_labels). We deliberately keep a small number of copied columns, mainly organization_id on child tables, for two reasons: the database can then reject cross-organization links, and the hot screens need no extra joins. Each copy is protected by a composite foreign key, so it cannot become inconsistent, which is the problem normalization exists to prevent.

