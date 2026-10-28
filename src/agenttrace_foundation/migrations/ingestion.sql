CREATE TABLE IF NOT EXISTS ingest_sources (
    source_ref uuid PRIMARY KEY,
    source_kind text NOT NULL CHECK(source_kind IN ('mailbox','exchange_audit','office_activity','graph_activity')),
    source_alias text NOT NULL CHECK(source_alias ~ '^[a-z][a-z0-9_-]{0,63}$'),
    binding_digest text NOT NULL,
    scope_cipher bytea NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS ingest_source_acl (
    source_ref uuid NOT NULL REFERENCES ingest_sources(source_ref),
    db_role text NOT NULL CHECK(db_role IN ('agenttrace_collector','agenttrace_api','agenttrace_attribution','agenttrace_content')),
    PRIMARY KEY(source_ref,db_role)
);
CREATE TABLE IF NOT EXISTS ingest_checkpoints (
    source_ref uuid NOT NULL REFERENCES ingest_sources(source_ref),
    partition_ref uuid NOT NULL,
    cursor_cipher bytea,
    watermark timestamptz,
    coverage text NOT NULL DEFAULT 'pending',
    reason_code text NOT NULL DEFAULT 'initial_sync_required',
    generation integer NOT NULL DEFAULT 0,
    lease uuid,
    lease_until timestamptz,
    last_success timestamptz,
    next_attempt timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(source_ref,partition_ref)
);
CREATE TABLE IF NOT EXISTS ingest_subscriptions (
    subscription_ref uuid PRIMARY KEY,
    source_ref uuid NOT NULL REFERENCES ingest_sources(source_ref),
    locator_cipher bytea NOT NULL,
    expires_at timestamptz NOT NULL,
    state text NOT NULL CHECK(state IN ('active','renewal_required','reauthorization_required','removed','expired')),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS ingest_events (
    event_ref uuid PRIMARY KEY,
    source_ref uuid NOT NULL REFERENCES ingest_sources(source_ref),
    kind text NOT NULL CHECK(kind IN ('created','updated','deleted','reauthorizationRequired','subscriptionRemoved','missed','audit_page')),
    locator_cipher bytea NOT NULL,
    event_time timestamptz,
    received_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL DEFAULT now()+interval '7 days',
    state text NOT NULL DEFAULT 'pending' CHECK(state IN ('pending','leased','retry','processed','poison')),
    attempts integer NOT NULL DEFAULT 0,
    receipt uuid,
    visible_at timestamptz NOT NULL DEFAULT now(),
    last_error_code text,
    CHECK(expires_at<=received_at+interval '7 days')
);
CREATE INDEX IF NOT EXISTS ingest_event_visibility ON ingest_events(visible_at) WHERE state IN ('pending','retry','leased');
CREATE TABLE IF NOT EXISTS ingest_copies (
    message_ref uuid PRIMARY KEY,
    source_ref uuid NOT NULL REFERENCES ingest_sources(source_ref),
    copy_key text NOT NULL,
    locator_cipher bytea NOT NULL,
    folder_ref uuid NOT NULL,
    delivery_ref uuid,
    current_version uuid,
    modified_at timestamptz NOT NULL,
    observed_at timestamptz NOT NULL DEFAULT now(),
    copy_role text NOT NULL CHECK(copy_role IN ('sender','recipient','unknown')),
    visibility text NOT NULL DEFAULT 'current' CHECK(visibility IN ('current','deleted_or_unavailable','moved_out_of_scope')),
    UNIQUE(source_ref,copy_key)
);
ALTER TABLE ingest_copies ADD COLUMN IF NOT EXISTS delivery_ref uuid;
CREATE TABLE IF NOT EXISTS ingest_versions (
    version_ref uuid PRIMARY KEY,
    source_ref uuid NOT NULL REFERENCES ingest_sources(source_ref),
    message_ref uuid NOT NULL REFERENCES ingest_copies(message_ref),
    change_digest text NOT NULL,
    content_digest text,
    summary jsonb NOT NULL,
    source_event_time timestamptz,
    received_at timestamptz NOT NULL DEFAULT now(),
    obsolete boolean NOT NULL DEFAULT false,
    expires_at timestamptz NOT NULL DEFAULT now()+interval '30 days',
    CHECK(expires_at<=received_at+interval '30 days'),
    CHECK((summary-'status'-'normalization_version'-'language'-'authored_words'-'word_bin'-'statistically_eligible'-'region_counts'-'reasons'-'excluded_attachment_count'-'offset_coordinate'-'scorer_state'-'is_draft')='{}'::jsonb),
    UNIQUE(message_ref,change_digest)
);
CREATE TABLE IF NOT EXISTS ingest_dispatch (
    version_ref uuid NOT NULL REFERENCES ingest_versions(version_ref),
    source_ref uuid NOT NULL REFERENCES ingest_sources(source_ref),
    axis text NOT NULL CHECK(axis IN ('agent','content')),
    state text NOT NULL DEFAULT 'pending' CHECK(state IN ('pending','leased','completed','superseded','expired')),
    receipt uuid,
    lease_until timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(version_ref,axis)
);
CREATE TABLE IF NOT EXISTS ingest_content_inputs (
    version_ref uuid PRIMARY KEY REFERENCES ingest_versions(version_ref),
    source_ref uuid NOT NULL REFERENCES ingest_sources(source_ref),
    capsule bytea NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    CHECK(expires_at<=created_at+interval '1 hour')
);
CREATE TABLE IF NOT EXISTS ingest_gaps (
    gap_ref uuid PRIMARY KEY,
    source_ref uuid NOT NULL REFERENCES ingest_sources(source_ref),
    partition_ref uuid,
    started_at timestamptz NOT NULL,
    ended_at timestamptz,
    reason_code text NOT NULL CHECK(reason_code ~ '^[a-z][a-z0-9_]{0,99}$'),
    disposition text NOT NULL CHECK(disposition IN ('open','recovered_current_state','unrecoverable')),
    known_lost_events integer,
    CHECK(known_lost_events IS NULL OR known_lost_events>=0)
);
CREATE TABLE IF NOT EXISTS ingest_audit_events (
    event_ref uuid PRIMARY KEY,
    source_ref uuid NOT NULL REFERENCES ingest_sources(source_ref),
    occurred_at timestamptz,
    received_at timestamptz NOT NULL DEFAULT now(),
    operation text NOT NULL CHECK(operation IN ('Send','Read','Other')),
    collector_action boolean NOT NULL,
    signal_eligible boolean NOT NULL,
    evidence_cipher bytea NOT NULL,
    expires_at timestamptz NOT NULL DEFAULT now()+interval '7 days',
    CHECK(expires_at<=received_at+interval '7 days')
);
CREATE TABLE IF NOT EXISTS ingest_transport_poison (
    event_ref uuid PRIMARY KEY,
    source_ref uuid NOT NULL REFERENCES ingest_sources(source_ref),
    payload_digest text NOT NULL,
    reason_code text NOT NULL CHECK(reason_code ~ '^[a-z][a-z0-9_]{0,99}$'),
    received_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL DEFAULT now()+interval '7 days'
);
-- Cross-source relationships must be valid even for direct SQL producers. RLS on
-- each row alone does not prevent a permitted row referring to another source.
CREATE UNIQUE INDEX IF NOT EXISTS ingest_copy_source_identity ON ingest_copies(message_ref,source_ref);
CREATE UNIQUE INDEX IF NOT EXISTS ingest_version_source_identity ON ingest_versions(version_ref,source_ref);
DO $$
BEGIN
    IF NOT EXISTS(SELECT 1 FROM pg_constraint WHERE conname='ingest_version_copy_source' AND conrelid='ingest_versions'::regclass) THEN
        ALTER TABLE ingest_versions ADD CONSTRAINT ingest_version_copy_source FOREIGN KEY(message_ref,source_ref) REFERENCES ingest_copies(message_ref,source_ref);
    END IF;
    IF NOT EXISTS(SELECT 1 FROM pg_constraint WHERE conname='ingest_dispatch_version_source' AND conrelid='ingest_dispatch'::regclass) THEN
        ALTER TABLE ingest_dispatch ADD CONSTRAINT ingest_dispatch_version_source FOREIGN KEY(version_ref,source_ref) REFERENCES ingest_versions(version_ref,source_ref);
    END IF;
    IF NOT EXISTS(SELECT 1 FROM pg_constraint WHERE conname='ingest_input_version_source' AND conrelid='ingest_content_inputs'::regclass) THEN
        ALTER TABLE ingest_content_inputs ADD CONSTRAINT ingest_input_version_source FOREIGN KEY(version_ref,source_ref) REFERENCES ingest_versions(version_ref,source_ref);
    END IF;
END $$;
