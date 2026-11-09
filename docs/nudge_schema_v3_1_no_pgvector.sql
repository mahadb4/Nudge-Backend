-- =====================================================================================
-- NUDGE  -  Automated Handling of Sales Pipeline
-- PostgreSQL 16 schema, ERD v3.1 (submitted ERD v3 + documented fixes, see docs/db-00)
-- 50 tables · 10 Django apps · every fixed choice is a smallint code with a CHECK
-- Run:  createdb nudge && psql -d nudge -v ON_ERROR_STOP=1 -f nudge_schema_v3_1.sql
-- =====================================================================================

BEGIN;

-- NO-PGVECTOR VARIANT: pgvector is not installed, so email_chunks.embedding is stored as real[] (384 numbers)
-- and has no similarity index yet. Everything else is identical to nudge_schema_v3_1.sql. When pgvector is
-- installed: ALTER TABLE email_chunks ALTER COLUMN embedding TYPE vector(384) USING embedding::vector(384);
-- then: CREATE INDEX ix_email_chunks_2 ON email_chunks USING hnsw (embedding vector_cosine_ops);

-- UUIDv7: time-ordered ids. Django generates them in Python (uuid6/uuid-utils);
-- this function is the same algorithm for raw SQL inserts, seeds and tests.
CREATE OR REPLACE FUNCTION nudge_uuid_v7() RETURNS uuid LANGUAGE sql VOLATILE PARALLEL SAFE AS $$
  SELECT encode(set_bit(set_bit(overlay(uuid_send(gen_random_uuid())
         PLACING substring(int8send((extract(epoch FROM clock_timestamp()) * 1000)::bigint) FROM 3)
         FROM 1 FOR 6), 52, 1), 53, 1), 'hex')::uuid;
$$;

-- =====================================================================================
-- Django app: accounts
-- =====================================================================================

-- organizations  (Midterm)  Tenant root: an individual account or a business account.
CREATE TABLE organizations (
    id                         uuid PRIMARY KEY DEFAULT nudge_uuid_v7(),
    name                       varchar(150) NOT NULL,
    account_type               smallint NOT NULL,
    timezone                   varchar(64) NOT NULL,
    automation_paused_at       timestamptz NULL,
    deactivated_at             timestamptz NULL,
    created_at                 timestamptz NOT NULL DEFAULT now(),
    updated_at                 timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_organizations_account_type CHECK (account_type IN (1,2))
);

-- users  (Midterm)  A person who can log in. Global (one login can belong to several organizations).
CREATE TABLE users (
    id                         uuid PRIMARY KEY DEFAULT nudge_uuid_v7(),
    email                      varchar(254) NOT NULL,
    password                   varchar(128) NOT NULL,
    full_name                  varchar(150) NOT NULL,
    phone                      varchar(20) NULL,
    avatar_path                varchar(500) NULL,
    timezone                   varchar(64) NOT NULL,
    quiet_hours_start          time NULL,
    quiet_hours_end            time NULL,
    is_active                  boolean NOT NULL DEFAULT true,
    is_staff                   boolean NOT NULL DEFAULT false,
    is_superuser               boolean NOT NULL DEFAULT false,
    email_verified_at          timestamptz NULL,
    last_login                 timestamptz NULL,
    created_at                 timestamptz NOT NULL DEFAULT now(),
    updated_at                 timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_users_email CHECK (email = lower(email)),
    CONSTRAINT ck_users_phone CHECK (phone IS NULL OR phone ~ '^\+[1-9][0-9]{7,14}$'),
    CONSTRAINT ck_users_quiet_hours_start_quiet_hours_end CHECK ((quiet_hours_start IS NULL) = (quiet_hours_end IS NULL))
);

-- user_sessions  (Midterm)  One row per logged-in device; holds the hash of the current refresh token.
CREATE TABLE user_sessions (
    id                         uuid PRIMARY KEY DEFAULT nudge_uuid_v7(),
    user_id                    uuid NOT NULL,
    refresh_token_hash         char(64) NOT NULL,
    device_name                varchar(100) NULL,
    ip_address                 inet NULL,
    expires_at                 timestamptz NOT NULL,
    last_used_at               timestamptz NULL,
    revoked_at                 timestamptz NULL,
    created_at                 timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_user_sessions_refresh_token_hash UNIQUE (refresh_token_hash),
    CONSTRAINT ck_user_sessions_expires_at_created_at CHECK (expires_at > created_at)
);

-- memberships  (Midterm)  Links a user to an organization with a role. Junction table users <-> organizations.
CREATE TABLE memberships (
    id                         uuid PRIMARY KEY DEFAULT nudge_uuid_v7(),
    organization_id            uuid NOT NULL,
    user_id                    uuid NOT NULL,
    role                       smallint NOT NULL,
    status                     smallint NOT NULL DEFAULT 1,
    created_at                 timestamptz NOT NULL DEFAULT now(),
    updated_at                 timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_memberships_organization_id_user_id UNIQUE (organization_id, user_id),
    CONSTRAINT uq_memberships_organization_id_id UNIQUE (organization_id, id),
    CONSTRAINT ck_memberships_role CHECK (role IN (1,2,3,4)),
    CONSTRAINT ck_memberships_status CHECK (status IN (1,2,3))
);

-- teams  (Midterm)  Departments inside a business organization, e.g. Sales, Finance.
CREATE TABLE teams (
    id                         uuid PRIMARY KEY DEFAULT nudge_uuid_v7(),
    organization_id            uuid NOT NULL,
    name                       varchar(80) NOT NULL,
    created_at                 timestamptz NOT NULL DEFAULT now(),
    updated_at                 timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_teams_organization_id_id UNIQUE (organization_id, id)
);

-- team_members  (Midterm)  Junction teams <-> memberships (many-to-many, Req 5.5).
CREATE TABLE team_members (
    id                         uuid PRIMARY KEY DEFAULT nudge_uuid_v7(),
    organization_id            uuid NOT NULL,
    team_id                    uuid NOT NULL,
    membership_id              uuid NOT NULL,
    is_lead                    boolean NOT NULL DEFAULT false,
    created_at                 timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_team_members_team_id_membership_id UNIQUE (team_id, membership_id)
);

-- invitations  (FYP-I)  Pending invitation of an email address to an organization.
CREATE TABLE invitations (
    id                         uuid PRIMARY KEY DEFAULT nudge_uuid_v7(),
    organization_id            uuid NOT NULL,
    email                      varchar(254) NOT NULL,
    role                       smallint NOT NULL,
    team_id                    uuid NULL,
    invited_by_id              uuid NOT NULL,
    token_hash                 char(64) NOT NULL,
    expires_at                 timestamptz NOT NULL,
    accepted_at                timestamptz NULL,
    created_at                 timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_invitations_token_hash UNIQUE (token_hash),
    CONSTRAINT ck_invitations_role CHECK (role IN (1,2,3,4)),
    CONSTRAINT ck_invitations_email CHECK (email = lower(email)),
    CONSTRAINT ck_invitations_expires_at_created_at CHECK (expires_at > created_at)
);

-- =====================================================================================
-- Django app: crm
-- =====================================================================================

-- companies  (Midterm)  Customer or prospect organization in the built-in CRM.
CREATE TABLE companies (
    id                         uuid PRIMARY KEY DEFAULT nudge_uuid_v7(),
    organization_id            uuid NOT NULL,
    owner_id                   uuid NOT NULL,
    team_id                    uuid NULL,
    visibility                 smallint NOT NULL DEFAULT 1,
    name                       varchar(150) NOT NULL,
    domain                     varchar(253) NULL,
    industry                   varchar(80) NULL,
    size_range                 smallint NULL,
    created_at                 timestamptz NOT NULL DEFAULT now(),
    updated_at                 timestamptz NOT NULL DEFAULT now(),
    deleted_at                 timestamptz NULL,
    CONSTRAINT uq_companies_organization_id_id UNIQUE (organization_id, id),
    CONSTRAINT ck_companies_visibility CHECK (visibility IN (1,2,3)),
    CONSTRAINT ck_companies_visibility_team_id CHECK ((visibility = 2) = (team_id IS NOT NULL)),
    CONSTRAINT ck_companies_size_range CHECK (size_range IS NULL OR size_range BETWEEN 1 AND 5),
    CONSTRAINT ck_companies_domain CHECK (domain = lower(domain))
);

-- contacts  (Midterm)  A person at a company (or independent) the user sells to.
CREATE TABLE contacts (
    id                         uuid PRIMARY KEY DEFAULT nudge_uuid_v7(),
    organization_id            uuid NOT NULL,
    company_id                 uuid NULL,
    owner_id                   uuid NOT NULL,
    team_id                    uuid NULL,
    visibility                 smallint NOT NULL DEFAULT 1,
    first_name                 varchar(80) NOT NULL,
    last_name                  varchar(80) NULL,
    email                      varchar(254) NULL,
    phone                      varchar(20) NULL,
    job_title                  varchar(100) NULL,
    source                     smallint NOT NULL DEFAULT 1,
    opted_out_at               timestamptz NULL,
    created_at                 timestamptz NOT NULL DEFAULT now(),
    updated_at                 timestamptz NOT NULL DEFAULT now(),
    deleted_at                 timestamptz NULL,
    CONSTRAINT uq_contacts_organization_id_id UNIQUE (organization_id, id),
    CONSTRAINT ck_contacts_visibility CHECK (visibility IN (1,2,3)),
    CONSTRAINT ck_contacts_visibility_team_id CHECK ((visibility = 2) = (team_id IS NOT NULL)),
    CONSTRAINT ck_contacts_source CHECK (source IN (1,2,3,4)),
    CONSTRAINT ck_contacts_email CHECK (email = lower(email)),
    CONSTRAINT ck_contacts_phone CHECK (phone IS NULL OR phone ~ '^\+[1-9][0-9]{7,14}$')
);

-- deal_stages  (Midterm)  Pipeline stages of an organization (lookup table, editable by Admins).
CREATE TABLE deal_stages (
    id                         uuid PRIMARY KEY DEFAULT nudge_uuid_v7(),
    organization_id            uuid NOT NULL,
    name                       varchar(60) NOT NULL,
    position                   smallint NOT NULL,
    outcome                    smallint NOT NULL DEFAULT 1,
    created_at                 timestamptz NOT NULL DEFAULT now(),
    updated_at                 timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_deal_stages_organization_id_id UNIQUE (organization_id, id),
    CONSTRAINT ck_deal_stages_outcome CHECK (outcome IN (1,2,3)),
    CONSTRAINT ck_deal_stages_position CHECK (position >= 0)
);

-- deals  (Midterm)  A sales opportunity moving through the pipeline.
CREATE TABLE deals (
    id                         uuid PRIMARY KEY DEFAULT nudge_uuid_v7(),
    organization_id            uuid NOT NULL,
    company_id                 uuid NULL,
    primary_contact_id         uuid NULL,
    stage_id                   uuid NOT NULL,
    owner_id                   uuid NOT NULL,
    team_id                    uuid NULL,
    visibility                 smallint NOT NULL DEFAULT 1,
    title                      varchar(150) NOT NULL,
    amount                     numeric(18,2) NULL,
    currency                   char(3) NOT NULL,
    expected_close_date        date NULL,
    closed_at                  timestamptz NULL,
    lost_reason                varchar(200) NULL,
    version                    integer NOT NULL DEFAULT 1,
    created_at                 timestamptz NOT NULL DEFAULT now(),
    updated_at                 timestamptz NOT NULL DEFAULT now(),
    deleted_at                 timestamptz NULL,
    CONSTRAINT uq_deals_organization_id_id UNIQUE (organization_id, id),
    CONSTRAINT ck_deals_visibility CHECK (visibility IN (1,2,3)),
    CONSTRAINT ck_deals_visibility_team_id CHECK ((visibility = 2) = (team_id IS NOT NULL)),
    CONSTRAINT ck_deals_amount CHECK (amount IS NULL OR amount >= 0),
    CONSTRAINT ck_deals_currency CHECK (currency ~ '^[A-Z]{3}$'),
    CONSTRAINT ck_deals_version CHECK (version >= 1)
);

-- activities  (FYP-II)  Timeline entries on a contact/deal (note, email, stage change, call).
CREATE TABLE activities (
    id                         uuid PRIMARY KEY DEFAULT nudge_uuid_v7(),
    organization_id            uuid NOT NULL,
    contact_id                 uuid NULL,
    deal_id                    uuid NULL,
    actor_id                   uuid NULL,
    message_id                 uuid NULL,
    type                       smallint NOT NULL,
    body                       text NULL,
    created_at                 timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_activities_organization_id_id UNIQUE (organization_id, id),
    CONSTRAINT ck_activities_type CHECK (type IN (1,2,3,4)),
    CONSTRAINT ck_activities_contact_id_deal_id CHECK (num_nonnulls(contact_id, deal_id) >= 1)
);

-- lead_forms  (FYP-I)  Embeddable web form that creates contacts.
CREATE TABLE lead_forms (
    id                         uuid PRIMARY KEY DEFAULT nudge_uuid_v7(),
    organization_id            uuid NOT NULL,
    team_id                    uuid NULL,
    name                       varchar(100) NOT NULL,
    fields                     jsonb NOT NULL DEFAULT '[]',
    public_key                 varchar(40) NOT NULL,
    is_active                  boolean NOT NULL DEFAULT true,
    created_at                 timestamptz NOT NULL DEFAULT now(),
    updated_at                 timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_lead_forms_public_key UNIQUE (public_key),
    CONSTRAINT uq_lead_forms_organization_id_id UNIQUE (organization_id, id),
    CONSTRAINT ck_lead_forms_fields CHECK (jsonb_typeof(fields) = 'array')
);

-- lead_submissions  (FYP-I)  One submitted web form.
CREATE TABLE lead_submissions (
    id                         uuid PRIMARY KEY DEFAULT nudge_uuid_v7(),
    organization_id            uuid NOT NULL,
    form_id                    uuid NOT NULL,
    contact_id                 uuid NULL,
    payload                    jsonb NOT NULL,
    ip_address                 inet NULL,
    submitted_at               timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_lead_submissions_payload CHECK (jsonb_typeof(payload) = 'object')
);

-- =====================================================================================
-- Django app: mail
-- =====================================================================================

-- email_accounts  (FYP-I)  A connected mailbox (Gmail, IMAP, Outlook).
CREATE TABLE email_accounts (
    id                         uuid PRIMARY KEY DEFAULT nudge_uuid_v7(),
    organization_id            uuid NOT NULL,
    owner_id                   uuid NOT NULL,
    team_id                    uuid NULL,
    provider                   smallint NOT NULL,
    email_address              varchar(254) NOT NULL,
    display_name               varchar(150) NULL,
    is_shared                  boolean NOT NULL DEFAULT false,
    credentials_encrypted      bytea NULL,
    sync_cursor                varchar(255) NULL,
    last_synced_at             timestamptz NULL,
    status                     smallint NOT NULL DEFAULT 1,
    last_error                 text NULL,
    created_at                 timestamptz NOT NULL DEFAULT now(),
    updated_at                 timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_email_accounts_organization_id_id UNIQUE (organization_id, id),
    CONSTRAINT ck_email_accounts_provider CHECK (provider IN (1,2,3)),
    CONSTRAINT ck_email_accounts_status CHECK (status IN (1,2,3)),
    CONSTRAINT ck_email_accounts_status_credentials_encrypted CHECK (status <> 3 OR credentials_encrypted IS NULL),
    CONSTRAINT ck_email_accounts_email_address CHECK (email_address = lower(email_address)),
    CONSTRAINT ck_email_accounts_team_id_is_shared CHECK (team_id IS NULL OR is_shared)
);

-- mailbox_access  (FYP-II)  Grants a member access to a shared mailbox (junction).
CREATE TABLE mailbox_access (
    id                         uuid PRIMARY KEY DEFAULT nudge_uuid_v7(),
    organization_id            uuid NOT NULL,
    email_account_id           uuid NOT NULL,
    user_id                    uuid NOT NULL,
    permission                 smallint NOT NULL,
    created_at                 timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_mailbox_access_email_account_id_user_id UNIQUE (email_account_id, user_id),
    CONSTRAINT ck_mailbox_access_permission CHECK (permission IN (1,2))
);

-- email_threads  (FYP-I)  A conversation in one mailbox.
CREATE TABLE email_threads (
    id                         uuid PRIMARY KEY DEFAULT nudge_uuid_v7(),
    organization_id            uuid NOT NULL,
    email_account_id           uuid NOT NULL,
    provider_thread_id         varchar(255) NOT NULL,
    subject                    text NULL,
    contact_id                 uuid NULL,
    deal_id                    uuid NULL,
    assigned_to_id             uuid NULL,
    last_message_at            timestamptz NOT NULL,
    status                     smallint NOT NULL DEFAULT 1,
    created_at                 timestamptz NOT NULL DEFAULT now(),
    updated_at                 timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_email_threads_email_account_id_provider_thread_id UNIQUE (email_account_id, provider_thread_id),
    CONSTRAINT uq_email_threads_email_account_id_id UNIQUE (email_account_id, id),
    CONSTRAINT uq_email_threads_organization_id_id UNIQUE (organization_id, id),
    CONSTRAINT ck_email_threads_status CHECK (status IN (1,2,3))
);

-- email_messages  (FYP-I)  One email (inbound or outbound).
CREATE TABLE email_messages (
    id                         uuid PRIMARY KEY DEFAULT nudge_uuid_v7(),
    organization_id            uuid NOT NULL,
    email_account_id           uuid NOT NULL,
    thread_id                  uuid NOT NULL,
    provider_message_id        varchar(255) NOT NULL,
    internet_message_id        text NULL,
    direction                  smallint NOT NULL,
    from_email                 varchar(254) NOT NULL,
    from_name                  varchar(150) NULL,
    subject                    text NULL,
    body_text                  text NULL,
    snippet                    varchar(200) NULL,
    sent_at                    timestamptz NOT NULL,
    has_attachments            boolean NOT NULL DEFAULT false,
    headers                    jsonb NOT NULL DEFAULT '{}',
    processing_status          smallint NOT NULL DEFAULT 1,
    processed_at               timestamptz NULL,
    search_tsv                 tsvector NOT NULL GENERATED ALWAYS AS (setweight(to_tsvector('english', coalesce(subject, '')), 'A') || setweight(to_tsvector('english', left(coalesce(body_text, ''), 200000)), 'B')) STORED,
    created_at                 timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_email_messages_email_account_id_provider_message_id UNIQUE (email_account_id, provider_message_id),
    CONSTRAINT uq_email_messages_organization_id_id UNIQUE (organization_id, id),
    CONSTRAINT uq_email_messages_email_account_id_id UNIQUE (email_account_id, id),
    CONSTRAINT ck_email_messages_direction CHECK (direction IN (1,2)),
    CONSTRAINT ck_email_messages_processing_status CHECK (processing_status IN (1,2,3,4)),
    CONSTRAINT ck_email_messages_from_email CHECK (from_email = lower(from_email))
);

-- message_recipients  (FYP-I)  To/Cc/Bcc addresses of a message.
CREATE TABLE message_recipients (
    id                         uuid PRIMARY KEY DEFAULT nudge_uuid_v7(),
    message_id                 uuid NOT NULL,
    email                      varchar(254) NOT NULL,
    name                       varchar(150) NULL,
    type                       smallint NOT NULL,
    CONSTRAINT uq_message_recipients_message_id_type_email UNIQUE (message_id, type, email),
    CONSTRAINT ck_message_recipients_type CHECK (type IN (1,2,3)),
    CONSTRAINT ck_message_recipients_email CHECK (email = lower(email))
);

-- =====================================================================================
-- Django app: ml
-- =====================================================================================

-- label_sets  (FYP-I)  A classification task (taxonomy). Global system data.
CREATE TABLE label_sets (
    id                         uuid PRIMARY KEY DEFAULT nudge_uuid_v7(),
    code                       varchar(30) NOT NULL,
    name                       varchar(60) NOT NULL,
    is_multi_label             boolean NOT NULL DEFAULT false,
    CONSTRAINT uq_label_sets_code UNIQUE (code)
);

-- labels  (FYP-I)  A label within a task, e.g. Meeting Request.
CREATE TABLE labels (
    id                         uuid PRIMARY KEY DEFAULT nudge_uuid_v7(),
    label_set_id               uuid NOT NULL,
    code                       varchar(40) NOT NULL,
    name                       varchar(60) NOT NULL,
    description                text NULL,
    position                   smallint NOT NULL DEFAULT 0,
    CONSTRAINT uq_labels_label_set_id_code UNIQUE (label_set_id, code)
);

-- ml_models  (FYP-I)  A versioned classifier: rules, TF-IDF+LR, DistilBERT or LLM prompt.
CREATE TABLE ml_models (
    id                         uuid PRIMARY KEY DEFAULT nudge_uuid_v7(),
    label_set_id               uuid NOT NULL,
    name                       varchar(60) NOT NULL,
    method                     smallint NOT NULL,
    version                    varchar(20) NOT NULL,
    config                     jsonb NOT NULL DEFAULT '{}',
    artifact_path              varchar(500) NULL,
    is_active                  boolean NOT NULL DEFAULT false,
    trained_at                 timestamptz NULL,
    created_at                 timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_ml_models_name_version UNIQUE (name, version),
    CONSTRAINT uq_ml_models_id_label_set_id UNIQUE (id, label_set_id),
    CONSTRAINT ck_ml_models_method CHECK (method IN (1,2,3,4))
);

-- evaluation_runs  (FYP-I)  One evaluation of a model on a fixed dataset split.
CREATE TABLE evaluation_runs (
    id                         uuid PRIMARY KEY DEFAULT nudge_uuid_v7(),
    model_id                   uuid NOT NULL,
    split                      smallint NOT NULL,
    test_set_hash              char(64) NOT NULL,
    item_count                 integer NOT NULL,
    threshold                  numeric(4,3) NULL,
    accuracy                   numeric(5,4) NOT NULL,
    macro_f1                   numeric(5,4) NOT NULL,
    coverage                   numeric(5,4) NULL,
    per_class                  jsonb NOT NULL,
    confusion_matrix           jsonb NOT NULL,
    notes                      text NULL,
    created_by_id              uuid NULL,
    created_at                 timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_evaluation_runs_split CHECK (split IN (2,3)),
    CONSTRAINT ck_evaluation_runs_item_count CHECK (item_count > 0),
    CONSTRAINT ck_evaluation_runs_accuracy_coverage CHECK (accuracy BETWEEN 0 AND 1 AND macro_f1 BETWEEN 0 AND 1 AND (coverage IS NULL OR coverage BETWEEN 0 AND 1))
);

-- predictions  (FYP-I)  One model's output for one message and one task.
CREATE TABLE predictions (
    id                         uuid PRIMARY KEY DEFAULT nudge_uuid_v7(),
    organization_id            uuid NOT NULL,
    message_id                 uuid NOT NULL,
    model_id                   uuid NOT NULL,
    label_set_id               uuid NOT NULL,
    decision_score             numeric(4,3) NOT NULL,
    status                     smallint NOT NULL,
    is_final                   boolean NOT NULL DEFAULT false,
    latency_ms                 integer NULL,
    created_at                 timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_predictions_message_id_model_id UNIQUE (message_id, model_id),
    CONSTRAINT uq_predictions_organization_id_id UNIQUE (organization_id, id),
    CONSTRAINT ck_predictions_decision_score CHECK (decision_score BETWEEN 0 AND 1),
    CONSTRAINT ck_predictions_status CHECK (status IN (1,2,3,4)),
    CONSTRAINT ck_predictions_latency_ms CHECK (latency_ms IS NULL OR latency_ms >= 0)
);

-- prediction_labels  (FYP-I)  Labels returned by a prediction with their scores (junction).
CREATE TABLE prediction_labels (
    id                         uuid PRIMARY KEY DEFAULT nudge_uuid_v7(),
    prediction_id              uuid NOT NULL,
    label_id                   uuid NOT NULL,
    score                      numeric(4,3) NOT NULL,
    is_primary                 boolean NOT NULL DEFAULT false,
    CONSTRAINT uq_prediction_labels_prediction_id_label_id UNIQUE (prediction_id, label_id),
    CONSTRAINT ck_prediction_labels_score CHECK (score BETWEEN 0 AND 1)
);

-- extractions  (FYP-I)  A detail extracted from a message, with its supporting evidence.
CREATE TABLE extractions (
    id                         uuid PRIMARY KEY DEFAULT nudge_uuid_v7(),
    organization_id            uuid NOT NULL,
    message_id                 uuid NOT NULL,
    prediction_id              uuid NULL,
    field_type                 smallint NOT NULL,
    value_text                 text NOT NULL,
    value_time                 timestamptz NULL,
    value_amount               numeric(18,2) NULL,
    currency                   char(3) NULL,
    evidence_text              text NOT NULL,
    evidence_start             integer NULL,
    evidence_end               integer NULL,
    confidence                 numeric(4,3) NULL,
    status                     smallint NOT NULL DEFAULT 1,
    created_at                 timestamptz NOT NULL DEFAULT now(),
    updated_at                 timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_extractions_organization_id_id UNIQUE (organization_id, id),
    CONSTRAINT ck_extractions_field_type CHECK (field_type BETWEEN 1 AND 8),
    CONSTRAINT ck_extractions_status CHECK (status IN (1,2,3,4)),
    CONSTRAINT ck_extractions_evidence_text CHECK (length(btrim(evidence_text)) > 0),
    CONSTRAINT ck_extractions_evidence_start_evidence_end CHECK ((evidence_start IS NULL) = (evidence_end IS NULL) AND (evidence_start IS NULL OR (evidence_start >= 0 AND evidence_end > evidence_start))),
    CONSTRAINT ck_extractions_value_amount_currency CHECK ((value_amount IS NULL) = (currency IS NULL) AND (currency IS NULL OR currency ~ '^[A-Z]{3}$'))
);

-- corrections  (FYP-I)  A user's correction of a label or an extracted detail.
CREATE TABLE corrections (
    id                         uuid PRIMARY KEY DEFAULT nudge_uuid_v7(),
    organization_id            uuid NOT NULL,
    prediction_id              uuid NULL,
    extraction_id              uuid NULL,
    user_id                    uuid NOT NULL,
    old_label_id               uuid NULL,
    new_label_id               uuid NULL,
    old_value                  text NULL,
    new_value                  text NULL,
    note                       text NULL,
    created_at                 timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_corrections_prediction_id_extraction_id CHECK (num_nonnulls(prediction_id, extraction_id) = 1),
    CONSTRAINT ck_corrections_prediction_id_new_label_id CHECK (prediction_id IS NULL OR new_label_id IS NOT NULL)
);

-- dataset_items  (FYP-I)  Training/evaluation example. Global research data (anonymised), not tenant data.
CREATE TABLE dataset_items (
    id                         uuid PRIMARY KEY DEFAULT nudge_uuid_v7(),
    source                     smallint NOT NULL,
    source_ref                 varchar(200) NULL,
    text                       text NOT NULL,
    content_hash               char(64) NOT NULL,
    group_key                  varchar(200) NOT NULL,
    split                      smallint NOT NULL,
    created_at                 timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_dataset_items_content_hash UNIQUE (content_hash),
    CONSTRAINT ck_dataset_items_source CHECK (source IN (1,2,3,4)),
    CONSTRAINT ck_dataset_items_split CHECK (split IN (1,2,3)),
    CONSTRAINT ck_dataset_items_split_source CHECK (NOT (split = 3 AND source = 3))
);

-- dataset_labels  (FYP-I)  A label given to a dataset item by a human, the LLM, or adjudication.
CREATE TABLE dataset_labels (
    id                         uuid PRIMARY KEY DEFAULT nudge_uuid_v7(),
    item_id                    uuid NOT NULL,
    label_id                   uuid NOT NULL,
    labeller_type              smallint NOT NULL,
    labelled_by_id             uuid NULL,
    model_id                   uuid NULL,
    created_at                 timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_dataset_labels_item_id_label_id_labeller_type_labelled_by_id UNIQUE NULLS NOT DISTINCT (item_id, label_id, labeller_type, labelled_by_id, model_id),
    CONSTRAINT ck_dataset_labels_labeller_type CHECK (labeller_type IN (1,2,3)),
    CONSTRAINT ck_dataset_labels_labeller_type_labelled_by_id CHECK (labeller_type = 2 OR labelled_by_id IS NOT NULL),
    CONSTRAINT ck_dataset_labels_labeller_type_model_id CHECK (labeller_type <> 2 OR model_id IS NOT NULL)
);

-- =====================================================================================
-- Django app: workflow
-- =====================================================================================

-- category_settings  (FYP-II)  Per-organization automation policy for each sales category: the 'safe to automate' decision.
CREATE TABLE category_settings (
    id                         uuid PRIMARY KEY DEFAULT nudge_uuid_v7(),
    organization_id            uuid NOT NULL,
    label_id                   uuid NOT NULL,
    mode                       smallint NOT NULL DEFAULT 2,
    min_score                  numeric(4,3) NOT NULL DEFAULT 0.900,
    hourly_cap                 smallint NOT NULL DEFAULT 5,
    daily_cap                  smallint NOT NULL DEFAULT 20,
    override_limit_pct         numeric(5,2) NULL,
    updated_by_id              uuid NULL,
    created_at                 timestamptz NOT NULL DEFAULT now(),
    updated_at                 timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_category_settings_organization_id_label_id UNIQUE (organization_id, label_id),
    CONSTRAINT ck_category_settings_mode CHECK (mode IN (1,2,3)),
    CONSTRAINT ck_category_settings_min_score CHECK (min_score BETWEEN 0 AND 1),
    CONSTRAINT ck_category_settings_hourly_cap_daily_cap CHECK (hourly_cap >= 0 AND daily_cap >= hourly_cap),
    CONSTRAINT ck_category_settings_override_limit_pct CHECK (override_limit_pct IS NULL OR override_limit_pct BETWEEN 0 AND 100)
);

-- email_templates  (FYP-I)  Reusable approved reply text.
CREATE TABLE email_templates (
    id                         uuid PRIMARY KEY DEFAULT nudge_uuid_v7(),
    organization_id            uuid NOT NULL,
    owner_id                   uuid NOT NULL,
    team_id                    uuid NULL,
    visibility                 smallint NOT NULL DEFAULT 1,
    name                       varchar(100) NOT NULL,
    subject                    text NULL,
    body                       text NOT NULL,
    intent_label_id            uuid NULL,
    created_at                 timestamptz NOT NULL DEFAULT now(),
    updated_at                 timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_email_templates_organization_id_id UNIQUE (organization_id, id),
    CONSTRAINT ck_email_templates_visibility CHECK (visibility IN (1,2,3)),
    CONSTRAINT ck_email_templates_visibility_team_id CHECK ((visibility = 2) = (team_id IS NOT NULL))
);

-- company_facts  (FYP-I)  Approved company information that drafts may use: prices, product facts, policies.
CREATE TABLE company_facts (
    id                         uuid PRIMARY KEY DEFAULT nudge_uuid_v7(),
    organization_id            uuid NOT NULL,
    label_id                   uuid NULL,
    kind                       smallint NOT NULL,
    title                      varchar(150) NOT NULL,
    body                       text NOT NULL,
    is_active                  boolean NOT NULL DEFAULT true,
    updated_by_id              uuid NULL,
    created_at                 timestamptz NOT NULL DEFAULT now(),
    updated_at                 timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_company_facts_kind CHECK (kind IN (1,2,3,4))
);

-- reply_drafts  (FYP-I)  AI-generated reply with edit, approval and send state.
CREATE TABLE reply_drafts (
    id                         uuid PRIMARY KEY DEFAULT nudge_uuid_v7(),
    organization_id            uuid NOT NULL,
    message_id                 uuid NOT NULL,
    prediction_id              uuid NULL,
    template_id                uuid NULL,
    original_body              text NOT NULL,
    body                       text NOT NULL,
    status                     smallint NOT NULL DEFAULT 1,
    send_mode                  smallint NOT NULL DEFAULT 1,
    approved_by_id             uuid NULL,
    approved_at                timestamptz NULL,
    send_after                 timestamptz NULL,
    idempotency_key            uuid NOT NULL,
    send_attempts              smallint NOT NULL DEFAULT 0,
    last_error                 text NULL,
    sent_at                    timestamptz NULL,
    sent_message_id            uuid NULL,
    created_at                 timestamptz NOT NULL DEFAULT now(),
    updated_at                 timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_reply_drafts_idempotency_key UNIQUE (idempotency_key),
    CONSTRAINT uq_reply_drafts_sent_message_id UNIQUE (sent_message_id),
    CONSTRAINT ck_reply_drafts_status CHECK (status IN (1,2,3,4,5)),
    CONSTRAINT ck_reply_drafts_send_mode CHECK (send_mode IN (1,2)),
    CONSTRAINT ck_reply_drafts_status_sent_at CHECK (status <> 3 OR sent_at IS NOT NULL),
    CONSTRAINT ck_reply_drafts_send_mode_status_approved_by_id CHECK (send_mode = 2 OR status NOT IN (2,3) OR approved_by_id IS NOT NULL),
    CONSTRAINT ck_reply_drafts_send_attempts CHECK (send_attempts >= 0),
    CONSTRAINT ck_reply_drafts_send_mode_status_send_after CHECK (send_mode <> 2 OR status <> 2 OR send_after IS NOT NULL)
);

-- follow_ups  (FYP-I)  Something someone must do or wait for, with a due time.
CREATE TABLE follow_ups (
    id                         uuid PRIMARY KEY DEFAULT nudge_uuid_v7(),
    organization_id            uuid NOT NULL,
    owner_id                   uuid NOT NULL,
    thread_id                  uuid NULL,
    deal_id                    uuid NULL,
    source_extraction_id       uuid NULL,
    type                       smallint NOT NULL,
    title                      varchar(200) NOT NULL,
    due_at                     timestamptz NOT NULL,
    status                     smallint NOT NULL DEFAULT 1,
    escalation_level           smallint NOT NULL DEFAULT 0,
    close_reason               smallint NULL,
    closed_at                  timestamptz NULL,
    created_by_ai              boolean NOT NULL DEFAULT false,
    created_at                 timestamptz NOT NULL DEFAULT now(),
    updated_at                 timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_follow_ups_organization_id_id UNIQUE (organization_id, id),
    CONSTRAINT ck_follow_ups_type CHECK (type IN (1,2,3,4)),
    CONSTRAINT ck_follow_ups_status CHECK (status IN (1,2,3,4)),
    CONSTRAINT ck_follow_ups_status_closed_at CHECK ((status IN (3,4)) = (closed_at IS NOT NULL)),
    CONSTRAINT ck_follow_ups_status_close_reason CHECK ((status IN (3,4)) = (close_reason IS NOT NULL)),
    CONSTRAINT ck_follow_ups_escalation_level CHECK (escalation_level BETWEEN 0 AND 5)
);

-- notification_channels  (FYP-I)  A user's reminder channel and its escalation order.
CREATE TABLE notification_channels (
    id                         uuid PRIMARY KEY DEFAULT nudge_uuid_v7(),
    user_id                    uuid NOT NULL,
    channel                    smallint NOT NULL,
    address                    varchar(254) NOT NULL,
    verified_at                timestamptz NULL,
    is_enabled                 boolean NOT NULL DEFAULT true,
    escalation_order           smallint NOT NULL DEFAULT 1,
    created_at                 timestamptz NOT NULL DEFAULT now(),
    updated_at                 timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_notification_channels_user_id_channel_address UNIQUE (user_id, channel, address),
    CONSTRAINT uq_notification_channels_user_id_id UNIQUE (user_id, id),
    CONSTRAINT ck_notification_channels_channel CHECK (channel IN (1,2,3,4,5)),
    CONSTRAINT ck_notification_channels_channel_verified_at_is_enabled CHECK (channel <> 5 OR verified_at IS NOT NULL OR NOT is_enabled)
);

-- notifications  (FYP-I)  One reminder to one user on one channel (NULL channel = in-app).
CREATE TABLE notifications (
    id                         uuid PRIMARY KEY DEFAULT nudge_uuid_v7(),
    organization_id            uuid NOT NULL,
    user_id                    uuid NOT NULL,
    follow_up_id               uuid NULL,
    channel_id                 uuid NULL,
    title                      varchar(200) NOT NULL,
    body                       text NULL,
    is_urgent                  boolean NOT NULL DEFAULT false,
    escalation_level           smallint NOT NULL DEFAULT 0,
    status                     smallint NOT NULL DEFAULT 1,
    attempts                   smallint NOT NULL DEFAULT 0,
    last_error                 text NULL,
    dedupe_key                 varchar(150) NULL,
    sent_at                    timestamptz NULL,
    read_at                    timestamptz NULL,
    created_at                 timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_notifications_dedupe_key UNIQUE (dedupe_key),
    CONSTRAINT uq_notifications_organization_id_id UNIQUE (organization_id, id),
    CONSTRAINT ck_notifications_status CHECK (status IN (1,2,3,4)),
    CONSTRAINT ck_notifications_status_sent_at_channel_id CHECK (status NOT IN (2,4) OR sent_at IS NOT NULL OR channel_id IS NULL),
    CONSTRAINT ck_notifications_status_read_at CHECK (status <> 4 OR read_at IS NOT NULL),
    CONSTRAINT ck_notifications_attempts CHECK (attempts >= 0)
);

-- call_logs  (FYP-II)  Automated reminder call placed to the user's own phone.
CREATE TABLE call_logs (
    id                         uuid PRIMARY KEY DEFAULT nudge_uuid_v7(),
    organization_id            uuid NOT NULL,
    notification_id            uuid NOT NULL,
    provider_call_id           varchar(100) NOT NULL,
    status                     smallint NOT NULL,
    started_at                 timestamptz NULL,
    duration_sec               integer NULL,
    transcript                 text NULL,
    outcome                    smallint NULL,
    created_at                 timestamptz NOT NULL DEFAULT now(),
    updated_at                 timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_call_logs_notification_id UNIQUE (notification_id),
    CONSTRAINT uq_call_logs_provider_call_id UNIQUE (provider_call_id),
    CONSTRAINT ck_call_logs_status CHECK (status IN (1,2,3,4)),
    CONSTRAINT ck_call_logs_outcome CHECK (outcome IS NULL OR outcome IN (1,2,3)),
    CONSTRAINT ck_call_logs_duration_sec CHECK (duration_sec IS NULL OR duration_sec >= 0)
);

-- =====================================================================================
-- Django app: assistant
-- =====================================================================================

-- email_chunks  (FYP-II)  Embedded text chunks for semantic search.
CREATE TABLE email_chunks (
    id                         uuid PRIMARY KEY DEFAULT nudge_uuid_v7(),
    organization_id            uuid NOT NULL,
    email_account_id           uuid NOT NULL,
    message_id                 uuid NOT NULL,
    chunk_index                smallint NOT NULL,
    content                    text NOT NULL,
    embedding                  real[] NOT NULL,
    created_at                 timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_email_chunks_message_id_chunk_index UNIQUE (message_id, chunk_index),
    CONSTRAINT ck_email_chunks_embedding_size CHECK (array_length(embedding, 1) = 384),
    CONSTRAINT ck_email_chunks_chunk_index CHECK (chunk_index >= 0)
);

-- assistant_conversations  (FYP-II)  A chat session with the assistant, private to its user.
CREATE TABLE assistant_conversations (
    id                         uuid PRIMARY KEY DEFAULT nudge_uuid_v7(),
    organization_id            uuid NOT NULL,
    user_id                    uuid NOT NULL,
    title                      varchar(150) NULL,
    created_at                 timestamptz NOT NULL DEFAULT now(),
    updated_at                 timestamptz NOT NULL DEFAULT now()
);

-- assistant_messages  (FYP-II)  A question or an answer in a conversation.
CREATE TABLE assistant_messages (
    id                         uuid PRIMARY KEY DEFAULT nudge_uuid_v7(),
    conversation_id            uuid NOT NULL,
    role                       smallint NOT NULL,
    content                    text NOT NULL,
    tool_used                  varchar(40) NULL,
    latency_ms                 integer NULL,
    created_at                 timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_assistant_messages_role CHECK (role IN (1,2))
);

-- assistant_citations  (FYP-II)  Source email or contact cited by an answer.
CREATE TABLE assistant_citations (
    id                         uuid PRIMARY KEY DEFAULT nudge_uuid_v7(),
    assistant_message_id       uuid NOT NULL,
    message_id                 uuid NULL,
    contact_id                 uuid NULL,
    CONSTRAINT ck_assistant_citations_message_id_contact_id CHECK (num_nonnulls(message_id, contact_id) = 1)
);

-- =====================================================================================
-- Django app: integrations
-- =====================================================================================

-- crm_connections  (FYP-II)  A connection to an external CRM (HubSpot).
CREATE TABLE crm_connections (
    id                         uuid PRIMARY KEY DEFAULT nudge_uuid_v7(),
    organization_id            uuid NOT NULL,
    provider                   smallint NOT NULL,
    credentials_encrypted      bytea NULL,
    status                     smallint NOT NULL DEFAULT 1,
    last_synced_at             timestamptz NULL,
    last_error                 text NULL,
    created_at                 timestamptz NOT NULL DEFAULT now(),
    updated_at                 timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_crm_connections_organization_id_provider UNIQUE (organization_id, provider),
    CONSTRAINT uq_crm_connections_organization_id_id UNIQUE (organization_id, id),
    CONSTRAINT ck_crm_connections_provider CHECK (provider IN (1,2)),
    CONSTRAINT ck_crm_connections_status CHECK (status IN (1,2,3)),
    CONSTRAINT ck_crm_connections_status_credentials_encrypted CHECK (status <> 3 OR credentials_encrypted IS NULL)
);

-- crm_stage_mappings  (FYP-II)  Maps a Nudge stage to a HubSpot stage.
CREATE TABLE crm_stage_mappings (
    id                         uuid PRIMARY KEY DEFAULT nudge_uuid_v7(),
    organization_id            uuid NOT NULL,
    connection_id              uuid NOT NULL,
    deal_stage_id              uuid NOT NULL,
    external_stage_id          varchar(100) NOT NULL,
    created_at                 timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_crm_stage_mappings_connection_id_deal_stage_id UNIQUE (connection_id, deal_stage_id)
);

-- external_links  (FYP-II)  External id of a pushed contact, deal or activity.
CREATE TABLE external_links (
    id                         uuid PRIMARY KEY DEFAULT nudge_uuid_v7(),
    organization_id            uuid NOT NULL,
    connection_id              uuid NOT NULL,
    contact_id                 uuid NULL,
    deal_id                    uuid NULL,
    activity_id                uuid NULL,
    external_id                varchar(100) NOT NULL,
    sync_status                smallint NOT NULL DEFAULT 1,
    last_error                 text NULL,
    synced_at                  timestamptz NULL,
    CONSTRAINT ck_external_links_contact_id_deal_id_activity_id CHECK (num_nonnulls(contact_id, deal_id, activity_id) = 1),
    CONSTRAINT ck_external_links_sync_status CHECK (sync_status IN (1,2,3))
);

-- =====================================================================================
-- Django app: audit
-- =====================================================================================

-- audit_logs  (FYP-I)  Append-only record of security- and business-relevant events.
CREATE TABLE audit_logs (
    id                         uuid PRIMARY KEY DEFAULT nudge_uuid_v7(),
    organization_id            uuid NULL,
    actor_id                   uuid NULL,
    actor_type                 smallint NOT NULL,
    action                     varchar(60) NOT NULL,
    object_type                varchar(40) NULL,
    object_id                  uuid NULL,
    details                    jsonb NOT NULL DEFAULT '{}',
    ip_address                 inet NULL,
    created_at                 timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_audit_logs_actor_type CHECK (actor_type IN (1,2,3)),
    CONSTRAINT ck_audit_logs_actor_type_actor_id CHECK (actor_type <> 1 OR actor_id IS NOT NULL),
    CONSTRAINT ck_audit_logs_action CHECK (action ~ '^[a-z_]+\.[a-z_]+$')
);

-- =====================================================================================
-- Django app: scheduling
-- =====================================================================================

-- meetings  (FYP-II)  A sales meeting: booked through the calendar, then held/no-show, with optional recording, transcript and notes.
CREATE TABLE meetings (
    id                         uuid PRIMARY KEY DEFAULT nudge_uuid_v7(),
    organization_id            uuid NOT NULL,
    deal_id                    uuid NULL,
    contact_id                 uuid NULL,
    organizer_id               uuid NOT NULL,
    title                      varchar(150) NOT NULL,
    starts_at                  timestamptz NOT NULL,
    ends_at                    timestamptz NOT NULL,
    status                     smallint NOT NULL DEFAULT 1,
    calendar_provider          smallint NULL,
    provider_event_id          varchar(255) NULL,
    audio_path                 varchar(500) NULL,
    audio_duration_sec         integer NULL,
    transcription_status       smallint NOT NULL DEFAULT 1,
    transcript                 text NULL,
    transcript_language        char(2) NULL,
    summary                    text NULL,
    created_at                 timestamptz NOT NULL DEFAULT now(),
    updated_at                 timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_meetings_organization_id_id UNIQUE (organization_id, id),
    CONSTRAINT ck_meetings_status CHECK (status IN (1,2,3,4)),
    CONSTRAINT ck_meetings_calendar_provider CHECK (calendar_provider IS NULL OR calendar_provider IN (1,2)),
    CONSTRAINT ck_meetings_transcription_status CHECK (transcription_status IN (1,2,3,4)),
    CONSTRAINT ck_meetings_ends_at_starts_at CHECK (ends_at > starts_at),
    CONSTRAINT ck_meetings_audio_duration_sec CHECK (audio_duration_sec IS NULL OR audio_duration_sec >= 0),
    CONSTRAINT ck_meetings_transcript_language CHECK (transcript_language IS NULL OR transcript_language ~ '^[a-z]{2}$'),
    CONSTRAINT ck_meetings_provider_event_id_calendar_provider CHECK ((provider_event_id IS NULL) = (calendar_provider IS NULL))
);

-- prospect_calls  (FYP-II)  Automated scheduling call to a prospect: confirm a booked meeting or recover a no-show.
CREATE TABLE prospect_calls (
    id                         uuid PRIMARY KEY DEFAULT nudge_uuid_v7(),
    organization_id            uuid NOT NULL,
    meeting_id                 uuid NULL,
    contact_id                 uuid NOT NULL,
    deal_id                    uuid NULL,
    purpose                    smallint NOT NULL,
    to_phone                   varchar(20) NOT NULL,
    provider_call_id           varchar(100) NULL,
    status                     smallint NOT NULL DEFAULT 1,
    disclosure_played          boolean NOT NULL DEFAULT false,
    started_at                 timestamptz NULL,
    ended_at                   timestamptz NULL,
    duration_sec               integer NULL,
    transcript                 text NULL,
    summary                    text NULL,
    outcome                    smallint NULL,
    handoff_to_id              uuid NULL,
    created_at                 timestamptz NOT NULL DEFAULT now(),
    updated_at                 timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_prospect_calls_provider_call_id UNIQUE (provider_call_id),
    CONSTRAINT ck_prospect_calls_purpose CHECK (purpose IN (1,2)),
    CONSTRAINT ck_prospect_calls_status CHECK (status IN (1,2,3,4,5)),
    CONSTRAINT ck_prospect_calls_outcome CHECK (outcome IS NULL OR outcome IN (1,2,3,4,5)),
    CONSTRAINT ck_prospect_calls_to_phone CHECK (to_phone ~ '^\+[1-9][0-9]{7,14}$'),
    CONSTRAINT ck_prospect_calls_duration_sec CHECK (duration_sec IS NULL OR duration_sec >= 0),
    CONSTRAINT ck_prospect_calls_ended_at_started_at CHECK (ended_at IS NULL OR started_at IS NULL OR ended_at >= started_at)
);

-- =====================================================================================
-- Django app: outreach
-- =====================================================================================

-- sequences  (FYP-II)  An outreach sequence: ordered follow-up emails sent until the contact replies.
CREATE TABLE sequences (
    id                         uuid PRIMARY KEY DEFAULT nudge_uuid_v7(),
    organization_id            uuid NOT NULL,
    owner_id                   uuid NOT NULL,
    name                       varchar(100) NOT NULL,
    is_active                  boolean NOT NULL DEFAULT true,
    created_at                 timestamptz NOT NULL DEFAULT now(),
    updated_at                 timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_sequences_organization_id_id UNIQUE (organization_id, id)
);

-- sequence_steps  (FYP-II)  One email step of a sequence.
CREATE TABLE sequence_steps (
    id                         uuid PRIMARY KEY DEFAULT nudge_uuid_v7(),
    organization_id            uuid NOT NULL,
    sequence_id                uuid NOT NULL,
    position                   smallint NOT NULL,
    delay_days                 smallint NOT NULL DEFAULT 0,
    template_id                uuid NOT NULL,
    created_at                 timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_sequence_steps_position CHECK (position >= 1),
    CONSTRAINT ck_sequence_steps_delay_days CHECK (delay_days >= 0)
);

-- sequence_enrollments  (FYP-II)  A contact enrolled in a sequence; stops automatically on reply or opt-out.
CREATE TABLE sequence_enrollments (
    id                         uuid PRIMARY KEY DEFAULT nudge_uuid_v7(),
    organization_id            uuid NOT NULL,
    sequence_id                uuid NOT NULL,
    contact_id                 uuid NOT NULL,
    email_account_id           uuid NOT NULL,
    current_step               smallint NOT NULL DEFAULT 0,
    status                     smallint NOT NULL DEFAULT 1,
    next_send_at               timestamptz NULL,
    created_at                 timestamptz NOT NULL DEFAULT now(),
    updated_at                 timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_sequence_enrollments_status CHECK (status IN (1,2,3,4,5)),
    CONSTRAINT ck_sequence_enrollments_current_step CHECK (current_step >= 0),
    CONSTRAINT ck_sequence_enrollments_status_next_send_at CHECK (status = 1 OR next_send_at IS NULL)
);

-- =====================================================================================
-- Foreign keys (138 single-column). Added after all tables exist so the crm <-> mail
-- reference (activities.message_id) needs no special ordering.
-- =====================================================================================
ALTER TABLE user_sessions ADD CONSTRAINT fk_user_sessions_user_id FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE;
ALTER TABLE memberships ADD CONSTRAINT fk_memberships_organization_id FOREIGN KEY (organization_id) REFERENCES organizations (id) ON DELETE RESTRICT;
ALTER TABLE memberships ADD CONSTRAINT fk_memberships_user_id FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE RESTRICT;
ALTER TABLE teams ADD CONSTRAINT fk_teams_organization_id FOREIGN KEY (organization_id) REFERENCES organizations (id) ON DELETE RESTRICT;
ALTER TABLE team_members ADD CONSTRAINT fk_team_members_organization_id FOREIGN KEY (organization_id) REFERENCES organizations (id) ON DELETE RESTRICT;
ALTER TABLE team_members ADD CONSTRAINT fk_team_members_team_id FOREIGN KEY (team_id) REFERENCES teams (id) ON DELETE CASCADE;
ALTER TABLE team_members ADD CONSTRAINT fk_team_members_membership_id FOREIGN KEY (membership_id) REFERENCES memberships (id) ON DELETE CASCADE;
ALTER TABLE invitations ADD CONSTRAINT fk_invitations_organization_id FOREIGN KEY (organization_id) REFERENCES organizations (id) ON DELETE RESTRICT;
ALTER TABLE invitations ADD CONSTRAINT fk_invitations_team_id FOREIGN KEY (team_id) REFERENCES teams (id) ON DELETE SET NULL;
ALTER TABLE invitations ADD CONSTRAINT fk_invitations_invited_by_id FOREIGN KEY (invited_by_id) REFERENCES users (id) ON DELETE RESTRICT;
ALTER TABLE companies ADD CONSTRAINT fk_companies_organization_id FOREIGN KEY (organization_id) REFERENCES organizations (id) ON DELETE RESTRICT;
ALTER TABLE companies ADD CONSTRAINT fk_companies_owner_id FOREIGN KEY (owner_id) REFERENCES users (id) ON DELETE RESTRICT;
ALTER TABLE companies ADD CONSTRAINT fk_companies_team_id FOREIGN KEY (team_id) REFERENCES teams (id) ON DELETE RESTRICT;
ALTER TABLE contacts ADD CONSTRAINT fk_contacts_organization_id FOREIGN KEY (organization_id) REFERENCES organizations (id) ON DELETE RESTRICT;
ALTER TABLE contacts ADD CONSTRAINT fk_contacts_company_id FOREIGN KEY (company_id) REFERENCES companies (id) ON DELETE SET NULL;
ALTER TABLE contacts ADD CONSTRAINT fk_contacts_owner_id FOREIGN KEY (owner_id) REFERENCES users (id) ON DELETE RESTRICT;
ALTER TABLE contacts ADD CONSTRAINT fk_contacts_team_id FOREIGN KEY (team_id) REFERENCES teams (id) ON DELETE RESTRICT;
ALTER TABLE deal_stages ADD CONSTRAINT fk_deal_stages_organization_id FOREIGN KEY (organization_id) REFERENCES organizations (id) ON DELETE RESTRICT;
ALTER TABLE deals ADD CONSTRAINT fk_deals_organization_id FOREIGN KEY (organization_id) REFERENCES organizations (id) ON DELETE RESTRICT;
ALTER TABLE deals ADD CONSTRAINT fk_deals_company_id FOREIGN KEY (company_id) REFERENCES companies (id) ON DELETE SET NULL;
ALTER TABLE deals ADD CONSTRAINT fk_deals_primary_contact_id FOREIGN KEY (primary_contact_id) REFERENCES contacts (id) ON DELETE SET NULL;
ALTER TABLE deals ADD CONSTRAINT fk_deals_stage_id FOREIGN KEY (stage_id) REFERENCES deal_stages (id) ON DELETE RESTRICT;
ALTER TABLE deals ADD CONSTRAINT fk_deals_owner_id FOREIGN KEY (owner_id) REFERENCES users (id) ON DELETE RESTRICT;
ALTER TABLE deals ADD CONSTRAINT fk_deals_team_id FOREIGN KEY (team_id) REFERENCES teams (id) ON DELETE RESTRICT;
ALTER TABLE activities ADD CONSTRAINT fk_activities_organization_id FOREIGN KEY (organization_id) REFERENCES organizations (id) ON DELETE RESTRICT;
ALTER TABLE activities ADD CONSTRAINT fk_activities_contact_id FOREIGN KEY (contact_id) REFERENCES contacts (id) ON DELETE CASCADE;
ALTER TABLE activities ADD CONSTRAINT fk_activities_deal_id FOREIGN KEY (deal_id) REFERENCES deals (id) ON DELETE CASCADE;
ALTER TABLE activities ADD CONSTRAINT fk_activities_actor_id FOREIGN KEY (actor_id) REFERENCES users (id) ON DELETE SET NULL;
ALTER TABLE activities ADD CONSTRAINT fk_activities_message_id FOREIGN KEY (message_id) REFERENCES email_messages (id) ON DELETE SET NULL;
ALTER TABLE lead_forms ADD CONSTRAINT fk_lead_forms_organization_id FOREIGN KEY (organization_id) REFERENCES organizations (id) ON DELETE RESTRICT;
ALTER TABLE lead_forms ADD CONSTRAINT fk_lead_forms_team_id FOREIGN KEY (team_id) REFERENCES teams (id) ON DELETE SET NULL;
ALTER TABLE lead_submissions ADD CONSTRAINT fk_lead_submissions_organization_id FOREIGN KEY (organization_id) REFERENCES organizations (id) ON DELETE RESTRICT;
ALTER TABLE lead_submissions ADD CONSTRAINT fk_lead_submissions_form_id FOREIGN KEY (form_id) REFERENCES lead_forms (id) ON DELETE CASCADE;
ALTER TABLE lead_submissions ADD CONSTRAINT fk_lead_submissions_contact_id FOREIGN KEY (contact_id) REFERENCES contacts (id) ON DELETE SET NULL;
ALTER TABLE email_accounts ADD CONSTRAINT fk_email_accounts_organization_id FOREIGN KEY (organization_id) REFERENCES organizations (id) ON DELETE RESTRICT;
ALTER TABLE email_accounts ADD CONSTRAINT fk_email_accounts_owner_id FOREIGN KEY (owner_id) REFERENCES users (id) ON DELETE RESTRICT;
ALTER TABLE email_accounts ADD CONSTRAINT fk_email_accounts_team_id FOREIGN KEY (team_id) REFERENCES teams (id) ON DELETE RESTRICT;
ALTER TABLE mailbox_access ADD CONSTRAINT fk_mailbox_access_organization_id FOREIGN KEY (organization_id) REFERENCES organizations (id) ON DELETE RESTRICT;
ALTER TABLE mailbox_access ADD CONSTRAINT fk_mailbox_access_email_account_id FOREIGN KEY (email_account_id) REFERENCES email_accounts (id) ON DELETE CASCADE;
ALTER TABLE mailbox_access ADD CONSTRAINT fk_mailbox_access_user_id FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE;
ALTER TABLE email_threads ADD CONSTRAINT fk_email_threads_organization_id FOREIGN KEY (organization_id) REFERENCES organizations (id) ON DELETE RESTRICT;
ALTER TABLE email_threads ADD CONSTRAINT fk_email_threads_email_account_id FOREIGN KEY (email_account_id) REFERENCES email_accounts (id) ON DELETE CASCADE;
ALTER TABLE email_threads ADD CONSTRAINT fk_email_threads_contact_id FOREIGN KEY (contact_id) REFERENCES contacts (id) ON DELETE SET NULL;
ALTER TABLE email_threads ADD CONSTRAINT fk_email_threads_deal_id FOREIGN KEY (deal_id) REFERENCES deals (id) ON DELETE SET NULL;
ALTER TABLE email_threads ADD CONSTRAINT fk_email_threads_assigned_to_id FOREIGN KEY (assigned_to_id) REFERENCES users (id) ON DELETE SET NULL;
ALTER TABLE email_messages ADD CONSTRAINT fk_email_messages_organization_id FOREIGN KEY (organization_id) REFERENCES organizations (id) ON DELETE RESTRICT;
ALTER TABLE email_messages ADD CONSTRAINT fk_email_messages_email_account_id FOREIGN KEY (email_account_id) REFERENCES email_accounts (id) ON DELETE CASCADE;
ALTER TABLE email_messages ADD CONSTRAINT fk_email_messages_thread_id FOREIGN KEY (thread_id) REFERENCES email_threads (id) ON DELETE CASCADE;
ALTER TABLE message_recipients ADD CONSTRAINT fk_message_recipients_message_id FOREIGN KEY (message_id) REFERENCES email_messages (id) ON DELETE CASCADE;
ALTER TABLE labels ADD CONSTRAINT fk_labels_label_set_id FOREIGN KEY (label_set_id) REFERENCES label_sets (id) ON DELETE RESTRICT;
ALTER TABLE ml_models ADD CONSTRAINT fk_ml_models_label_set_id FOREIGN KEY (label_set_id) REFERENCES label_sets (id) ON DELETE RESTRICT;
ALTER TABLE evaluation_runs ADD CONSTRAINT fk_evaluation_runs_model_id FOREIGN KEY (model_id) REFERENCES ml_models (id) ON DELETE RESTRICT;
ALTER TABLE evaluation_runs ADD CONSTRAINT fk_evaluation_runs_created_by_id FOREIGN KEY (created_by_id) REFERENCES users (id) ON DELETE SET NULL;
ALTER TABLE predictions ADD CONSTRAINT fk_predictions_organization_id FOREIGN KEY (organization_id) REFERENCES organizations (id) ON DELETE RESTRICT;
ALTER TABLE predictions ADD CONSTRAINT fk_predictions_message_id FOREIGN KEY (message_id) REFERENCES email_messages (id) ON DELETE CASCADE;
ALTER TABLE predictions ADD CONSTRAINT fk_predictions_model_id FOREIGN KEY (model_id) REFERENCES ml_models (id) ON DELETE RESTRICT;
ALTER TABLE predictions ADD CONSTRAINT fk_predictions_label_set_id FOREIGN KEY (label_set_id) REFERENCES label_sets (id) ON DELETE RESTRICT;
ALTER TABLE prediction_labels ADD CONSTRAINT fk_prediction_labels_prediction_id FOREIGN KEY (prediction_id) REFERENCES predictions (id) ON DELETE CASCADE;
ALTER TABLE prediction_labels ADD CONSTRAINT fk_prediction_labels_label_id FOREIGN KEY (label_id) REFERENCES labels (id) ON DELETE RESTRICT;
ALTER TABLE extractions ADD CONSTRAINT fk_extractions_organization_id FOREIGN KEY (organization_id) REFERENCES organizations (id) ON DELETE RESTRICT;
ALTER TABLE extractions ADD CONSTRAINT fk_extractions_message_id FOREIGN KEY (message_id) REFERENCES email_messages (id) ON DELETE CASCADE;
ALTER TABLE extractions ADD CONSTRAINT fk_extractions_prediction_id FOREIGN KEY (prediction_id) REFERENCES predictions (id) ON DELETE SET NULL;
ALTER TABLE corrections ADD CONSTRAINT fk_corrections_organization_id FOREIGN KEY (organization_id) REFERENCES organizations (id) ON DELETE RESTRICT;
ALTER TABLE corrections ADD CONSTRAINT fk_corrections_prediction_id FOREIGN KEY (prediction_id) REFERENCES predictions (id) ON DELETE CASCADE;
ALTER TABLE corrections ADD CONSTRAINT fk_corrections_extraction_id FOREIGN KEY (extraction_id) REFERENCES extractions (id) ON DELETE CASCADE;
ALTER TABLE corrections ADD CONSTRAINT fk_corrections_user_id FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE RESTRICT;
ALTER TABLE corrections ADD CONSTRAINT fk_corrections_old_label_id FOREIGN KEY (old_label_id) REFERENCES labels (id) ON DELETE RESTRICT;
ALTER TABLE corrections ADD CONSTRAINT fk_corrections_new_label_id FOREIGN KEY (new_label_id) REFERENCES labels (id) ON DELETE RESTRICT;
ALTER TABLE dataset_labels ADD CONSTRAINT fk_dataset_labels_item_id FOREIGN KEY (item_id) REFERENCES dataset_items (id) ON DELETE CASCADE;
ALTER TABLE dataset_labels ADD CONSTRAINT fk_dataset_labels_label_id FOREIGN KEY (label_id) REFERENCES labels (id) ON DELETE RESTRICT;
ALTER TABLE dataset_labels ADD CONSTRAINT fk_dataset_labels_labelled_by_id FOREIGN KEY (labelled_by_id) REFERENCES users (id) ON DELETE RESTRICT;
ALTER TABLE dataset_labels ADD CONSTRAINT fk_dataset_labels_model_id FOREIGN KEY (model_id) REFERENCES ml_models (id) ON DELETE RESTRICT;
ALTER TABLE category_settings ADD CONSTRAINT fk_category_settings_organization_id FOREIGN KEY (organization_id) REFERENCES organizations (id) ON DELETE RESTRICT;
ALTER TABLE category_settings ADD CONSTRAINT fk_category_settings_label_id FOREIGN KEY (label_id) REFERENCES labels (id) ON DELETE RESTRICT;
ALTER TABLE category_settings ADD CONSTRAINT fk_category_settings_updated_by_id FOREIGN KEY (updated_by_id) REFERENCES users (id) ON DELETE SET NULL;
ALTER TABLE email_templates ADD CONSTRAINT fk_email_templates_organization_id FOREIGN KEY (organization_id) REFERENCES organizations (id) ON DELETE RESTRICT;
ALTER TABLE email_templates ADD CONSTRAINT fk_email_templates_owner_id FOREIGN KEY (owner_id) REFERENCES users (id) ON DELETE RESTRICT;
ALTER TABLE email_templates ADD CONSTRAINT fk_email_templates_team_id FOREIGN KEY (team_id) REFERENCES teams (id) ON DELETE RESTRICT;
ALTER TABLE email_templates ADD CONSTRAINT fk_email_templates_intent_label_id FOREIGN KEY (intent_label_id) REFERENCES labels (id) ON DELETE SET NULL;
ALTER TABLE company_facts ADD CONSTRAINT fk_company_facts_organization_id FOREIGN KEY (organization_id) REFERENCES organizations (id) ON DELETE RESTRICT;
ALTER TABLE company_facts ADD CONSTRAINT fk_company_facts_label_id FOREIGN KEY (label_id) REFERENCES labels (id) ON DELETE SET NULL;
ALTER TABLE company_facts ADD CONSTRAINT fk_company_facts_updated_by_id FOREIGN KEY (updated_by_id) REFERENCES users (id) ON DELETE SET NULL;
ALTER TABLE reply_drafts ADD CONSTRAINT fk_reply_drafts_organization_id FOREIGN KEY (organization_id) REFERENCES organizations (id) ON DELETE RESTRICT;
ALTER TABLE reply_drafts ADD CONSTRAINT fk_reply_drafts_message_id FOREIGN KEY (message_id) REFERENCES email_messages (id) ON DELETE CASCADE;
ALTER TABLE reply_drafts ADD CONSTRAINT fk_reply_drafts_prediction_id FOREIGN KEY (prediction_id) REFERENCES predictions (id) ON DELETE SET NULL;
ALTER TABLE reply_drafts ADD CONSTRAINT fk_reply_drafts_template_id FOREIGN KEY (template_id) REFERENCES email_templates (id) ON DELETE SET NULL;
ALTER TABLE reply_drafts ADD CONSTRAINT fk_reply_drafts_approved_by_id FOREIGN KEY (approved_by_id) REFERENCES users (id) ON DELETE SET NULL;
ALTER TABLE reply_drafts ADD CONSTRAINT fk_reply_drafts_sent_message_id FOREIGN KEY (sent_message_id) REFERENCES email_messages (id) ON DELETE SET NULL;
ALTER TABLE follow_ups ADD CONSTRAINT fk_follow_ups_organization_id FOREIGN KEY (organization_id) REFERENCES organizations (id) ON DELETE RESTRICT;
ALTER TABLE follow_ups ADD CONSTRAINT fk_follow_ups_owner_id FOREIGN KEY (owner_id) REFERENCES users (id) ON DELETE RESTRICT;
ALTER TABLE follow_ups ADD CONSTRAINT fk_follow_ups_thread_id FOREIGN KEY (thread_id) REFERENCES email_threads (id) ON DELETE CASCADE;
ALTER TABLE follow_ups ADD CONSTRAINT fk_follow_ups_deal_id FOREIGN KEY (deal_id) REFERENCES deals (id) ON DELETE SET NULL;
ALTER TABLE follow_ups ADD CONSTRAINT fk_follow_ups_source_extraction_id FOREIGN KEY (source_extraction_id) REFERENCES extractions (id) ON DELETE SET NULL;
ALTER TABLE notification_channels ADD CONSTRAINT fk_notification_channels_user_id FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE;
ALTER TABLE notifications ADD CONSTRAINT fk_notifications_organization_id FOREIGN KEY (organization_id) REFERENCES organizations (id) ON DELETE RESTRICT;
ALTER TABLE notifications ADD CONSTRAINT fk_notifications_user_id FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE;
ALTER TABLE notifications ADD CONSTRAINT fk_notifications_follow_up_id FOREIGN KEY (follow_up_id) REFERENCES follow_ups (id) ON DELETE CASCADE;
ALTER TABLE notifications ADD CONSTRAINT fk_notifications_channel_id FOREIGN KEY (channel_id) REFERENCES notification_channels (id) ON DELETE SET NULL;
ALTER TABLE call_logs ADD CONSTRAINT fk_call_logs_organization_id FOREIGN KEY (organization_id) REFERENCES organizations (id) ON DELETE RESTRICT;
ALTER TABLE call_logs ADD CONSTRAINT fk_call_logs_notification_id FOREIGN KEY (notification_id) REFERENCES notifications (id) ON DELETE CASCADE;
ALTER TABLE email_chunks ADD CONSTRAINT fk_email_chunks_organization_id FOREIGN KEY (organization_id) REFERENCES organizations (id) ON DELETE RESTRICT;
ALTER TABLE email_chunks ADD CONSTRAINT fk_email_chunks_email_account_id FOREIGN KEY (email_account_id) REFERENCES email_accounts (id) ON DELETE CASCADE;
ALTER TABLE email_chunks ADD CONSTRAINT fk_email_chunks_message_id FOREIGN KEY (message_id) REFERENCES email_messages (id) ON DELETE CASCADE;
ALTER TABLE assistant_conversations ADD CONSTRAINT fk_assistant_conversations_organization_id FOREIGN KEY (organization_id) REFERENCES organizations (id) ON DELETE RESTRICT;
ALTER TABLE assistant_conversations ADD CONSTRAINT fk_assistant_conversations_user_id FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE;
ALTER TABLE assistant_messages ADD CONSTRAINT fk_assistant_messages_conversation_id FOREIGN KEY (conversation_id) REFERENCES assistant_conversations (id) ON DELETE CASCADE;
ALTER TABLE assistant_citations ADD CONSTRAINT fk_assistant_citations_assistant_message_id FOREIGN KEY (assistant_message_id) REFERENCES assistant_messages (id) ON DELETE CASCADE;
ALTER TABLE assistant_citations ADD CONSTRAINT fk_assistant_citations_message_id FOREIGN KEY (message_id) REFERENCES email_messages (id) ON DELETE CASCADE;
ALTER TABLE assistant_citations ADD CONSTRAINT fk_assistant_citations_contact_id FOREIGN KEY (contact_id) REFERENCES contacts (id) ON DELETE CASCADE;
ALTER TABLE crm_connections ADD CONSTRAINT fk_crm_connections_organization_id FOREIGN KEY (organization_id) REFERENCES organizations (id) ON DELETE RESTRICT;
ALTER TABLE crm_stage_mappings ADD CONSTRAINT fk_crm_stage_mappings_organization_id FOREIGN KEY (organization_id) REFERENCES organizations (id) ON DELETE RESTRICT;
ALTER TABLE crm_stage_mappings ADD CONSTRAINT fk_crm_stage_mappings_connection_id FOREIGN KEY (connection_id) REFERENCES crm_connections (id) ON DELETE CASCADE;
ALTER TABLE crm_stage_mappings ADD CONSTRAINT fk_crm_stage_mappings_deal_stage_id FOREIGN KEY (deal_stage_id) REFERENCES deal_stages (id) ON DELETE CASCADE;
ALTER TABLE external_links ADD CONSTRAINT fk_external_links_organization_id FOREIGN KEY (organization_id) REFERENCES organizations (id) ON DELETE RESTRICT;
ALTER TABLE external_links ADD CONSTRAINT fk_external_links_connection_id FOREIGN KEY (connection_id) REFERENCES crm_connections (id) ON DELETE CASCADE;
ALTER TABLE external_links ADD CONSTRAINT fk_external_links_contact_id FOREIGN KEY (contact_id) REFERENCES contacts (id) ON DELETE CASCADE;
ALTER TABLE external_links ADD CONSTRAINT fk_external_links_deal_id FOREIGN KEY (deal_id) REFERENCES deals (id) ON DELETE CASCADE;
ALTER TABLE external_links ADD CONSTRAINT fk_external_links_activity_id FOREIGN KEY (activity_id) REFERENCES activities (id) ON DELETE CASCADE;
ALTER TABLE audit_logs ADD CONSTRAINT fk_audit_logs_organization_id FOREIGN KEY (organization_id) REFERENCES organizations (id) ON DELETE RESTRICT;
ALTER TABLE audit_logs ADD CONSTRAINT fk_audit_logs_actor_id FOREIGN KEY (actor_id) REFERENCES users (id) ON DELETE RESTRICT;
ALTER TABLE meetings ADD CONSTRAINT fk_meetings_organization_id FOREIGN KEY (organization_id) REFERENCES organizations (id) ON DELETE RESTRICT;
ALTER TABLE meetings ADD CONSTRAINT fk_meetings_deal_id FOREIGN KEY (deal_id) REFERENCES deals (id) ON DELETE SET NULL;
ALTER TABLE meetings ADD CONSTRAINT fk_meetings_contact_id FOREIGN KEY (contact_id) REFERENCES contacts (id) ON DELETE SET NULL;
ALTER TABLE meetings ADD CONSTRAINT fk_meetings_organizer_id FOREIGN KEY (organizer_id) REFERENCES users (id) ON DELETE RESTRICT;
ALTER TABLE prospect_calls ADD CONSTRAINT fk_prospect_calls_organization_id FOREIGN KEY (organization_id) REFERENCES organizations (id) ON DELETE RESTRICT;
ALTER TABLE prospect_calls ADD CONSTRAINT fk_prospect_calls_meeting_id FOREIGN KEY (meeting_id) REFERENCES meetings (id) ON DELETE SET NULL;
ALTER TABLE prospect_calls ADD CONSTRAINT fk_prospect_calls_contact_id FOREIGN KEY (contact_id) REFERENCES contacts (id) ON DELETE CASCADE;
ALTER TABLE prospect_calls ADD CONSTRAINT fk_prospect_calls_deal_id FOREIGN KEY (deal_id) REFERENCES deals (id) ON DELETE SET NULL;
ALTER TABLE prospect_calls ADD CONSTRAINT fk_prospect_calls_handoff_to_id FOREIGN KEY (handoff_to_id) REFERENCES users (id) ON DELETE SET NULL;
ALTER TABLE sequences ADD CONSTRAINT fk_sequences_organization_id FOREIGN KEY (organization_id) REFERENCES organizations (id) ON DELETE RESTRICT;
ALTER TABLE sequences ADD CONSTRAINT fk_sequences_owner_id FOREIGN KEY (owner_id) REFERENCES users (id) ON DELETE RESTRICT;
ALTER TABLE sequence_steps ADD CONSTRAINT fk_sequence_steps_organization_id FOREIGN KEY (organization_id) REFERENCES organizations (id) ON DELETE RESTRICT;
ALTER TABLE sequence_steps ADD CONSTRAINT fk_sequence_steps_sequence_id FOREIGN KEY (sequence_id) REFERENCES sequences (id) ON DELETE CASCADE;
ALTER TABLE sequence_steps ADD CONSTRAINT fk_sequence_steps_template_id FOREIGN KEY (template_id) REFERENCES email_templates (id) ON DELETE RESTRICT;
ALTER TABLE sequence_enrollments ADD CONSTRAINT fk_sequence_enrollments_organization_id FOREIGN KEY (organization_id) REFERENCES organizations (id) ON DELETE RESTRICT;
ALTER TABLE sequence_enrollments ADD CONSTRAINT fk_sequence_enrollments_sequence_id FOREIGN KEY (sequence_id) REFERENCES sequences (id) ON DELETE CASCADE;
ALTER TABLE sequence_enrollments ADD CONSTRAINT fk_sequence_enrollments_contact_id FOREIGN KEY (contact_id) REFERENCES contacts (id) ON DELETE CASCADE;
ALTER TABLE sequence_enrollments ADD CONSTRAINT fk_sequence_enrollments_email_account_id FOREIGN KEY (email_account_id) REFERENCES email_accounts (id) ON DELETE CASCADE;

-- =====================================================================================
-- Composite tenant / consistency foreign keys (77)
-- A child row can only point at a parent in the SAME organization (or mailbox / user / task).
-- DEFERRABLE INITIALLY DEFERRED so Django's own ON DELETE handling runs first; checked at COMMIT.
-- =====================================================================================
ALTER TABLE team_members ADD CONSTRAINT fkt_team_members_team_id FOREIGN KEY (organization_id, team_id) REFERENCES teams (organization_id, id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE team_members ADD CONSTRAINT fkt_team_members_membership_id FOREIGN KEY (organization_id, membership_id) REFERENCES memberships (organization_id, id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE invitations ADD CONSTRAINT fkt_invitations_team_id FOREIGN KEY (organization_id, team_id) REFERENCES teams (organization_id, id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE invitations ADD CONSTRAINT fkt_invitations_invited_by_id FOREIGN KEY (organization_id, invited_by_id) REFERENCES memberships (organization_id, user_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE companies ADD CONSTRAINT fkt_companies_owner_id FOREIGN KEY (organization_id, owner_id) REFERENCES memberships (organization_id, user_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE companies ADD CONSTRAINT fkt_companies_team_id FOREIGN KEY (organization_id, team_id) REFERENCES teams (organization_id, id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE contacts ADD CONSTRAINT fkt_contacts_company_id FOREIGN KEY (organization_id, company_id) REFERENCES companies (organization_id, id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE contacts ADD CONSTRAINT fkt_contacts_owner_id FOREIGN KEY (organization_id, owner_id) REFERENCES memberships (organization_id, user_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE contacts ADD CONSTRAINT fkt_contacts_team_id FOREIGN KEY (organization_id, team_id) REFERENCES teams (organization_id, id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE deals ADD CONSTRAINT fkt_deals_company_id FOREIGN KEY (organization_id, company_id) REFERENCES companies (organization_id, id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE deals ADD CONSTRAINT fkt_deals_primary_contact_id FOREIGN KEY (organization_id, primary_contact_id) REFERENCES contacts (organization_id, id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE deals ADD CONSTRAINT fkt_deals_stage_id FOREIGN KEY (organization_id, stage_id) REFERENCES deal_stages (organization_id, id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE deals ADD CONSTRAINT fkt_deals_owner_id FOREIGN KEY (organization_id, owner_id) REFERENCES memberships (organization_id, user_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE deals ADD CONSTRAINT fkt_deals_team_id FOREIGN KEY (organization_id, team_id) REFERENCES teams (organization_id, id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE activities ADD CONSTRAINT fkt_activities_contact_id FOREIGN KEY (organization_id, contact_id) REFERENCES contacts (organization_id, id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE activities ADD CONSTRAINT fkt_activities_deal_id FOREIGN KEY (organization_id, deal_id) REFERENCES deals (organization_id, id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE activities ADD CONSTRAINT fkt_activities_actor_id FOREIGN KEY (organization_id, actor_id) REFERENCES memberships (organization_id, user_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE activities ADD CONSTRAINT fkt_activities_message_id FOREIGN KEY (organization_id, message_id) REFERENCES email_messages (organization_id, id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE lead_forms ADD CONSTRAINT fkt_lead_forms_team_id FOREIGN KEY (organization_id, team_id) REFERENCES teams (organization_id, id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE lead_submissions ADD CONSTRAINT fkt_lead_submissions_form_id FOREIGN KEY (organization_id, form_id) REFERENCES lead_forms (organization_id, id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE lead_submissions ADD CONSTRAINT fkt_lead_submissions_contact_id FOREIGN KEY (organization_id, contact_id) REFERENCES contacts (organization_id, id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE email_accounts ADD CONSTRAINT fkt_email_accounts_owner_id FOREIGN KEY (organization_id, owner_id) REFERENCES memberships (organization_id, user_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE email_accounts ADD CONSTRAINT fkt_email_accounts_team_id FOREIGN KEY (organization_id, team_id) REFERENCES teams (organization_id, id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE mailbox_access ADD CONSTRAINT fkt_mailbox_access_email_account_id FOREIGN KEY (organization_id, email_account_id) REFERENCES email_accounts (organization_id, id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE mailbox_access ADD CONSTRAINT fkt_mailbox_access_user_id FOREIGN KEY (organization_id, user_id) REFERENCES memberships (organization_id, user_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE email_threads ADD CONSTRAINT fkt_email_threads_email_account_id FOREIGN KEY (organization_id, email_account_id) REFERENCES email_accounts (organization_id, id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE email_threads ADD CONSTRAINT fkt_email_threads_contact_id FOREIGN KEY (organization_id, contact_id) REFERENCES contacts (organization_id, id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE email_threads ADD CONSTRAINT fkt_email_threads_deal_id FOREIGN KEY (organization_id, deal_id) REFERENCES deals (organization_id, id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE email_threads ADD CONSTRAINT fkt_email_threads_assigned_to_id FOREIGN KEY (organization_id, assigned_to_id) REFERENCES memberships (organization_id, user_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE email_messages ADD CONSTRAINT fkt_email_messages_email_account_id FOREIGN KEY (organization_id, email_account_id) REFERENCES email_accounts (organization_id, id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE email_messages ADD CONSTRAINT fkt_email_messages_thread_id FOREIGN KEY (email_account_id, thread_id) REFERENCES email_threads (email_account_id, id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE predictions ADD CONSTRAINT fkt_predictions_message_id FOREIGN KEY (organization_id, message_id) REFERENCES email_messages (organization_id, id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE predictions ADD CONSTRAINT fkt_predictions_label_set_id FOREIGN KEY (model_id, label_set_id) REFERENCES ml_models (id, label_set_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE extractions ADD CONSTRAINT fkt_extractions_message_id FOREIGN KEY (organization_id, message_id) REFERENCES email_messages (organization_id, id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE extractions ADD CONSTRAINT fkt_extractions_prediction_id FOREIGN KEY (organization_id, prediction_id) REFERENCES predictions (organization_id, id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE corrections ADD CONSTRAINT fkt_corrections_prediction_id FOREIGN KEY (organization_id, prediction_id) REFERENCES predictions (organization_id, id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE corrections ADD CONSTRAINT fkt_corrections_extraction_id FOREIGN KEY (organization_id, extraction_id) REFERENCES extractions (organization_id, id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE corrections ADD CONSTRAINT fkt_corrections_user_id FOREIGN KEY (organization_id, user_id) REFERENCES memberships (organization_id, user_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE category_settings ADD CONSTRAINT fkt_category_settings_updated_by_id FOREIGN KEY (organization_id, updated_by_id) REFERENCES memberships (organization_id, user_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE email_templates ADD CONSTRAINT fkt_email_templates_owner_id FOREIGN KEY (organization_id, owner_id) REFERENCES memberships (organization_id, user_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE email_templates ADD CONSTRAINT fkt_email_templates_team_id FOREIGN KEY (organization_id, team_id) REFERENCES teams (organization_id, id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE company_facts ADD CONSTRAINT fkt_company_facts_updated_by_id FOREIGN KEY (organization_id, updated_by_id) REFERENCES memberships (organization_id, user_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE reply_drafts ADD CONSTRAINT fkt_reply_drafts_message_id FOREIGN KEY (organization_id, message_id) REFERENCES email_messages (organization_id, id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE reply_drafts ADD CONSTRAINT fkt_reply_drafts_prediction_id FOREIGN KEY (organization_id, prediction_id) REFERENCES predictions (organization_id, id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE reply_drafts ADD CONSTRAINT fkt_reply_drafts_template_id FOREIGN KEY (organization_id, template_id) REFERENCES email_templates (organization_id, id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE reply_drafts ADD CONSTRAINT fkt_reply_drafts_approved_by_id FOREIGN KEY (organization_id, approved_by_id) REFERENCES memberships (organization_id, user_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE reply_drafts ADD CONSTRAINT fkt_reply_drafts_sent_message_id FOREIGN KEY (organization_id, sent_message_id) REFERENCES email_messages (organization_id, id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE follow_ups ADD CONSTRAINT fkt_follow_ups_owner_id FOREIGN KEY (organization_id, owner_id) REFERENCES memberships (organization_id, user_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE follow_ups ADD CONSTRAINT fkt_follow_ups_thread_id FOREIGN KEY (organization_id, thread_id) REFERENCES email_threads (organization_id, id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE follow_ups ADD CONSTRAINT fkt_follow_ups_deal_id FOREIGN KEY (organization_id, deal_id) REFERENCES deals (organization_id, id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE follow_ups ADD CONSTRAINT fkt_follow_ups_source_extraction_id FOREIGN KEY (organization_id, source_extraction_id) REFERENCES extractions (organization_id, id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE notifications ADD CONSTRAINT fkt_notifications_user_id FOREIGN KEY (organization_id, user_id) REFERENCES memberships (organization_id, user_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE notifications ADD CONSTRAINT fkt_notifications_follow_up_id FOREIGN KEY (organization_id, follow_up_id) REFERENCES follow_ups (organization_id, id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE notifications ADD CONSTRAINT fkt_notifications_channel_id FOREIGN KEY (user_id, channel_id) REFERENCES notification_channels (user_id, id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE call_logs ADD CONSTRAINT fkt_call_logs_notification_id FOREIGN KEY (organization_id, notification_id) REFERENCES notifications (organization_id, id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE email_chunks ADD CONSTRAINT fkt_email_chunks_email_account_id FOREIGN KEY (organization_id, email_account_id) REFERENCES email_accounts (organization_id, id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE email_chunks ADD CONSTRAINT fkt_email_chunks_message_id FOREIGN KEY (email_account_id, message_id) REFERENCES email_messages (email_account_id, id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE assistant_conversations ADD CONSTRAINT fkt_assistant_conversations_user_id FOREIGN KEY (organization_id, user_id) REFERENCES memberships (organization_id, user_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE crm_stage_mappings ADD CONSTRAINT fkt_crm_stage_mappings_connection_id FOREIGN KEY (organization_id, connection_id) REFERENCES crm_connections (organization_id, id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE crm_stage_mappings ADD CONSTRAINT fkt_crm_stage_mappings_deal_stage_id FOREIGN KEY (organization_id, deal_stage_id) REFERENCES deal_stages (organization_id, id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE external_links ADD CONSTRAINT fkt_external_links_connection_id FOREIGN KEY (organization_id, connection_id) REFERENCES crm_connections (organization_id, id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE external_links ADD CONSTRAINT fkt_external_links_contact_id FOREIGN KEY (organization_id, contact_id) REFERENCES contacts (organization_id, id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE external_links ADD CONSTRAINT fkt_external_links_deal_id FOREIGN KEY (organization_id, deal_id) REFERENCES deals (organization_id, id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE external_links ADD CONSTRAINT fkt_external_links_activity_id FOREIGN KEY (organization_id, activity_id) REFERENCES activities (organization_id, id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE meetings ADD CONSTRAINT fkt_meetings_deal_id FOREIGN KEY (organization_id, deal_id) REFERENCES deals (organization_id, id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE meetings ADD CONSTRAINT fkt_meetings_contact_id FOREIGN KEY (organization_id, contact_id) REFERENCES contacts (organization_id, id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE meetings ADD CONSTRAINT fkt_meetings_organizer_id FOREIGN KEY (organization_id, organizer_id) REFERENCES memberships (organization_id, user_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE prospect_calls ADD CONSTRAINT fkt_prospect_calls_meeting_id FOREIGN KEY (organization_id, meeting_id) REFERENCES meetings (organization_id, id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE prospect_calls ADD CONSTRAINT fkt_prospect_calls_contact_id FOREIGN KEY (organization_id, contact_id) REFERENCES contacts (organization_id, id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE prospect_calls ADD CONSTRAINT fkt_prospect_calls_deal_id FOREIGN KEY (organization_id, deal_id) REFERENCES deals (organization_id, id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE prospect_calls ADD CONSTRAINT fkt_prospect_calls_handoff_to_id FOREIGN KEY (organization_id, handoff_to_id) REFERENCES memberships (organization_id, user_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE sequences ADD CONSTRAINT fkt_sequences_owner_id FOREIGN KEY (organization_id, owner_id) REFERENCES memberships (organization_id, user_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE sequence_steps ADD CONSTRAINT fkt_sequence_steps_sequence_id FOREIGN KEY (organization_id, sequence_id) REFERENCES sequences (organization_id, id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE sequence_steps ADD CONSTRAINT fkt_sequence_steps_template_id FOREIGN KEY (organization_id, template_id) REFERENCES email_templates (organization_id, id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE sequence_enrollments ADD CONSTRAINT fkt_sequence_enrollments_sequence_id FOREIGN KEY (organization_id, sequence_id) REFERENCES sequences (organization_id, id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE sequence_enrollments ADD CONSTRAINT fkt_sequence_enrollments_contact_id FOREIGN KEY (organization_id, contact_id) REFERENCES contacts (organization_id, id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE sequence_enrollments ADD CONSTRAINT fkt_sequence_enrollments_email_account_id FOREIGN KEY (organization_id, email_account_id) REFERENCES email_accounts (organization_id, id) DEFERRABLE INITIALLY DEFERRED;

-- =====================================================================================
-- Secondary indexes (from the ERD; each one serves a named screen or job)
-- =====================================================================================
CREATE UNIQUE INDEX uq_users_1 ON users (email);
CREATE INDEX ix_user_sessions_1 ON user_sessions (user_id, expires_at) WHERE revoked_at IS NULL;
CREATE INDEX ix_memberships_2 ON memberships (user_id);
CREATE UNIQUE INDEX uq_teams_1 ON teams (organization_id, lower(name));
CREATE INDEX ix_team_members_2 ON team_members (membership_id);
CREATE INDEX ix_invitations_1 ON invitations (organization_id, email);
CREATE UNIQUE INDEX uq_companies_1 ON companies (organization_id, domain) WHERE deleted_at IS NULL AND domain IS NOT NULL;
CREATE INDEX ix_companies_2 ON companies (organization_id, lower(name)) WHERE deleted_at IS NULL;
CREATE INDEX ix_companies_3 ON companies (organization_id, owner_id) WHERE deleted_at IS NULL;
CREATE INDEX ix_companies_4 ON companies (organization_id, team_id) WHERE deleted_at IS NULL AND team_id IS NOT NULL;
CREATE UNIQUE INDEX uq_contacts_1 ON contacts (organization_id, email) WHERE deleted_at IS NULL AND email IS NOT NULL;
CREATE INDEX ix_contacts_2 ON contacts (organization_id, lower(last_name), lower(first_name));
CREATE INDEX ix_contacts_3 ON contacts (organization_id, owner_id) WHERE deleted_at IS NULL;
CREATE INDEX ix_contacts_4 ON contacts (organization_id, company_id) WHERE deleted_at IS NULL AND company_id IS NOT NULL;
CREATE INDEX ix_contacts_5 ON contacts (organization_id, team_id) WHERE deleted_at IS NULL AND team_id IS NOT NULL;
CREATE UNIQUE INDEX uq_deal_stages_1 ON deal_stages (organization_id, lower(name));
CREATE INDEX ix_deals_1 ON deals (organization_id, stage_id, id) WHERE deleted_at IS NULL;
CREATE INDEX ix_deals_2 ON deals (organization_id, owner_id) WHERE deleted_at IS NULL;
CREATE INDEX ix_deals_3 ON deals (organization_id, company_id) WHERE deleted_at IS NULL AND company_id IS NOT NULL;
CREATE INDEX ix_deals_4 ON deals (organization_id, primary_contact_id) WHERE deleted_at IS NULL AND primary_contact_id IS NOT NULL;
CREATE INDEX ix_deals_5 ON deals (organization_id, team_id) WHERE deleted_at IS NULL AND team_id IS NOT NULL;
CREATE INDEX ix_activities_1 ON activities (deal_id, created_at DESC);
CREATE INDEX ix_activities_2 ON activities (contact_id, created_at DESC);
CREATE INDEX ix_lead_submissions_1 ON lead_submissions (form_id, submitted_at DESC);
CREATE UNIQUE INDEX uq_email_accounts_1 ON email_accounts (organization_id, email_address);
CREATE INDEX ix_email_accounts_2 ON email_accounts (organization_id, owner_id);
CREATE INDEX ix_mailbox_access_2 ON mailbox_access (user_id);
CREATE INDEX ix_email_threads_2 ON email_threads (email_account_id, last_message_at DESC);
CREATE INDEX ix_email_threads_3 ON email_threads (organization_id, contact_id) WHERE contact_id IS NOT NULL;
CREATE INDEX ix_email_threads_4 ON email_threads (organization_id, deal_id) WHERE deal_id IS NOT NULL;
CREATE INDEX ix_email_messages_2 ON email_messages (thread_id, sent_at);
CREATE INDEX ix_email_messages_3 ON email_messages (organization_id, from_email);
CREATE INDEX ix_email_messages_4 ON email_messages (internet_message_id) WHERE internet_message_id IS NOT NULL;
CREATE INDEX ix_email_messages_5 ON email_messages (processing_status) WHERE processing_status IN (1,3);
CREATE INDEX ix_email_messages_6 ON email_messages USING gin (search_tsv);
CREATE INDEX ix_message_recipients_2 ON message_recipients (email);
CREATE UNIQUE INDEX uq_ml_models_2 ON ml_models (label_set_id) WHERE is_active;
CREATE INDEX ix_evaluation_runs_1 ON evaluation_runs (model_id, created_at DESC);
CREATE UNIQUE INDEX uq_predictions_2 ON predictions (message_id, label_set_id) WHERE is_final;
CREATE INDEX ix_predictions_3 ON predictions (organization_id, created_at) WHERE status = 2 AND is_final;
CREATE UNIQUE INDEX uq_prediction_labels_2 ON prediction_labels (prediction_id) WHERE is_primary;
CREATE INDEX ix_prediction_labels_3 ON prediction_labels (label_id);
CREATE INDEX ix_extractions_1 ON extractions (message_id);
CREATE INDEX ix_corrections_1 ON corrections (prediction_id) WHERE prediction_id IS NOT NULL;
CREATE INDEX ix_corrections_2 ON corrections (organization_id, created_at);
CREATE INDEX ix_dataset_items_2 ON dataset_items (group_key);
CREATE INDEX ix_email_templates_1 ON email_templates (organization_id, intent_label_id);
CREATE INDEX ix_company_facts_1 ON company_facts (organization_id, kind) WHERE is_active;
CREATE INDEX ix_reply_drafts_1 ON reply_drafts (message_id);
CREATE INDEX ix_reply_drafts_2 ON reply_drafts (send_after) WHERE status = 2;
CREATE INDEX ix_reply_drafts_3 ON reply_drafts (organization_id, send_mode, sent_at) WHERE status = 3;
CREATE UNIQUE INDEX uq_follow_ups_1 ON follow_ups (thread_id, type) WHERE status IN (1,2) AND thread_id IS NOT NULL AND type IN (1,2);
CREATE INDEX ix_follow_ups_2 ON follow_ups (owner_id, due_at) WHERE status IN (1,2);
CREATE INDEX ix_follow_ups_3 ON follow_ups (due_at) WHERE status IN (1,2);
CREATE INDEX ix_notifications_1 ON notifications (user_id, status, created_at DESC);
CREATE INDEX ix_notifications_2 ON notifications (created_at) WHERE status = 1;
-- (HNSW index ix_email_chunks_2 is added after pgvector is installed)
CREATE INDEX ix_email_chunks_3 ON email_chunks (organization_id, email_account_id);
CREATE INDEX ix_assistant_conversations_1 ON assistant_conversations (user_id, updated_at DESC);
CREATE INDEX ix_assistant_messages_1 ON assistant_messages (conversation_id, created_at);
CREATE INDEX ix_assistant_citations_1 ON assistant_citations (assistant_message_id);
CREATE UNIQUE INDEX uq_external_links_1 ON external_links (connection_id, contact_id) WHERE contact_id IS NOT NULL;
CREATE UNIQUE INDEX uq_external_links_2 ON external_links (connection_id, deal_id) WHERE deal_id IS NOT NULL;
CREATE UNIQUE INDEX uq_external_links_3 ON external_links (connection_id, activity_id) WHERE activity_id IS NOT NULL;
CREATE INDEX ix_external_links_4 ON external_links (connection_id, sync_status) WHERE sync_status IN (2,3);
CREATE INDEX ix_audit_logs_1 ON audit_logs (organization_id, created_at DESC);
CREATE INDEX ix_audit_logs_2 ON audit_logs (organization_id, action, created_at DESC);
CREATE INDEX ix_audit_logs_3 ON audit_logs (organization_id, actor_id, created_at DESC);
CREATE INDEX ix_audit_logs_4 ON audit_logs (object_type, object_id);
CREATE UNIQUE INDEX uq_meetings_1 ON meetings (organization_id, calendar_provider, provider_event_id) WHERE provider_event_id IS NOT NULL;
CREATE INDEX ix_meetings_2 ON meetings (organization_id, starts_at);
CREATE INDEX ix_meetings_3 ON meetings (deal_id) WHERE deal_id IS NOT NULL;
CREATE INDEX ix_prospect_calls_1 ON prospect_calls (organization_id, contact_id);
CREATE INDEX ix_prospect_calls_2 ON prospect_calls (meeting_id) WHERE meeting_id IS NOT NULL;
CREATE UNIQUE INDEX uq_sequences_1 ON sequences (organization_id, lower(name));
CREATE UNIQUE INDEX uq_sequence_steps_1 ON sequence_steps (sequence_id, position);
CREATE UNIQUE INDEX uq_sequence_enrollments_1 ON sequence_enrollments (sequence_id, contact_id) WHERE status = 1;
CREATE INDEX ix_sequence_enrollments_2 ON sequence_enrollments (next_send_at) WHERE status = 1;
-- P18 (L10): sequence_id cascades from sequences; the partial unique index (status = 1) cannot serve that check.
CREATE INDEX ix_sequence_enrollments_sequence_id_fk ON sequence_enrollments (sequence_id);

-- FK columns not covered by any index above. PostgreSQL does not index FKs by itself; an index is
-- needed when the parent row can really be deleted (the ON DELETE check scans the child table).
-- Not indexed on purpose (write speed): FKs whose parent is never hard-deleted and that no screen
-- filters on alone - organizations, users, label_sets, labels, ml_models. In Django these FKs
-- use db_index=False. Nullable FKs get a partial index (WHERE col IS NOT NULL): smaller and cheaper.
CREATE INDEX ix_invitations_team_id_fk ON invitations (team_id) WHERE team_id IS NOT NULL;
CREATE INDEX ix_companies_team_id_fk ON companies (team_id) WHERE team_id IS NOT NULL;
CREATE INDEX ix_contacts_company_id_fk ON contacts (company_id) WHERE company_id IS NOT NULL;
CREATE INDEX ix_contacts_team_id_fk ON contacts (team_id) WHERE team_id IS NOT NULL;
CREATE INDEX ix_deals_company_id_fk ON deals (company_id) WHERE company_id IS NOT NULL;
CREATE INDEX ix_deals_primary_contact_id_fk ON deals (primary_contact_id) WHERE primary_contact_id IS NOT NULL;
CREATE INDEX ix_deals_stage_id_fk ON deals (stage_id);
CREATE INDEX ix_deals_team_id_fk ON deals (team_id) WHERE team_id IS NOT NULL;
CREATE INDEX ix_activities_message_id_fk ON activities (message_id) WHERE message_id IS NOT NULL;
CREATE INDEX ix_lead_forms_team_id_fk ON lead_forms (team_id) WHERE team_id IS NOT NULL;
CREATE INDEX ix_lead_submissions_contact_id_fk ON lead_submissions (contact_id) WHERE contact_id IS NOT NULL;
CREATE INDEX ix_email_accounts_team_id_fk ON email_accounts (team_id) WHERE team_id IS NOT NULL;
CREATE INDEX ix_email_threads_contact_id_fk ON email_threads (contact_id) WHERE contact_id IS NOT NULL;
CREATE INDEX ix_email_threads_deal_id_fk ON email_threads (deal_id) WHERE deal_id IS NOT NULL;
CREATE INDEX ix_extractions_prediction_id_fk ON extractions (prediction_id) WHERE prediction_id IS NOT NULL;
CREATE INDEX ix_corrections_extraction_id_fk ON corrections (extraction_id) WHERE extraction_id IS NOT NULL;
CREATE INDEX ix_email_templates_team_id_fk ON email_templates (team_id) WHERE team_id IS NOT NULL;
CREATE INDEX ix_reply_drafts_prediction_id_fk ON reply_drafts (prediction_id) WHERE prediction_id IS NOT NULL;
CREATE INDEX ix_reply_drafts_template_id_fk ON reply_drafts (template_id) WHERE template_id IS NOT NULL;
CREATE INDEX ix_follow_ups_deal_id_fk ON follow_ups (deal_id) WHERE deal_id IS NOT NULL;
CREATE INDEX ix_follow_ups_source_extraction_id_fk ON follow_ups (source_extraction_id) WHERE source_extraction_id IS NOT NULL;
CREATE INDEX ix_notifications_follow_up_id_fk ON notifications (follow_up_id) WHERE follow_up_id IS NOT NULL;
CREATE INDEX ix_notifications_channel_id_fk ON notifications (channel_id) WHERE channel_id IS NOT NULL;
CREATE INDEX ix_email_chunks_email_account_id_fk ON email_chunks (email_account_id);
CREATE INDEX ix_assistant_citations_message_id_fk ON assistant_citations (message_id) WHERE message_id IS NOT NULL;
CREATE INDEX ix_assistant_citations_contact_id_fk ON assistant_citations (contact_id) WHERE contact_id IS NOT NULL;
CREATE INDEX ix_crm_stage_mappings_deal_stage_id_fk ON crm_stage_mappings (deal_stage_id);
CREATE INDEX ix_external_links_contact_id_fk ON external_links (contact_id) WHERE contact_id IS NOT NULL;
CREATE INDEX ix_external_links_deal_id_fk ON external_links (deal_id) WHERE deal_id IS NOT NULL;
CREATE INDEX ix_external_links_activity_id_fk ON external_links (activity_id) WHERE activity_id IS NOT NULL;
CREATE INDEX ix_meetings_contact_id_fk ON meetings (contact_id) WHERE contact_id IS NOT NULL;
CREATE INDEX ix_prospect_calls_contact_id_fk ON prospect_calls (contact_id);
CREATE INDEX ix_prospect_calls_deal_id_fk ON prospect_calls (deal_id) WHERE deal_id IS NOT NULL;
CREATE INDEX ix_sequence_steps_template_id_fk ON sequence_steps (template_id);
CREATE INDEX ix_sequence_enrollments_contact_id_fk ON sequence_enrollments (contact_id);
CREATE INDEX ix_sequence_enrollments_email_account_id_fk ON sequence_enrollments (email_account_id);

-- =====================================================================================
-- audit_logs is append-only: UPDATE and DELETE are refused (REQ-AU-04).
-- In production also: REVOKE UPDATE, DELETE ON audit_logs FROM nudge_app;
-- =====================================================================================
CREATE OR REPLACE FUNCTION nudge_audit_logs_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'audit_logs is append-only';
END;
$$;
CREATE TRIGGER trg_audit_logs_append_only BEFORE UPDATE OR DELETE ON audit_logs
  FOR EACH ROW EXECUTE FUNCTION nudge_audit_logs_append_only();
-- P17 (L7): TRUNCATE is refused too. Django TransactionTestCase flushes with TRUNCATE: use TestCase.
CREATE TRIGGER trg_audit_logs_no_truncate BEFORE TRUNCATE ON audit_logs
  FOR EACH STATEMENT EXECUTE FUNCTION nudge_audit_logs_append_only();

-- =====================================================================================
-- P13 (M8): one thread / sender group can never be split across train, validation and test (REQ-DT-03).
-- =====================================================================================
CREATE EXTENSION IF NOT EXISTS btree_gist;
ALTER TABLE dataset_items ADD CONSTRAINT ex_dataset_items_group_split EXCLUDE USING gist (group_key WITH =, split WITH <>);

-- =====================================================================================
-- P22 (H2): assistant_citations has no organization_id, so a trigger checks that the cited email or
-- contact belongs to the same organization as the conversation (NFR-SEC-03). No new column.
-- =====================================================================================
CREATE OR REPLACE FUNCTION nudge_citation_same_org() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE conv_org uuid; cited_org uuid;
BEGIN
  SELECT c.organization_id INTO conv_org FROM assistant_messages m JOIN assistant_conversations c ON c.id = m.conversation_id
   WHERE m.id = NEW.assistant_message_id;
  IF NEW.message_id IS NOT NULL THEN SELECT organization_id INTO cited_org FROM email_messages WHERE id = NEW.message_id;
  ELSE SELECT organization_id INTO cited_org FROM contacts WHERE id = NEW.contact_id; END IF;
  IF conv_org IS DISTINCT FROM cited_org THEN
    RAISE EXCEPTION 'assistant citation must point at the same organization' USING ERRCODE = 'foreign_key_violation';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER trg_assistant_citations_same_org BEFORE INSERT OR UPDATE ON assistant_citations
  FOR EACH ROW EXECUTE FUNCTION nudge_citation_same_org();

COMMIT;
