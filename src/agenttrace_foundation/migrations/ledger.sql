-- Append-only evidence and independently versioned decision inputs. No message text.
CREATE TABLE IF NOT EXISTS ledger_schema(version integer PRIMARY KEY CHECK(version=1));
INSERT INTO ledger_schema VALUES(1) ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS ledger_scopes (
    scope_ref uuid PRIMARY KEY, tenant_id uuid NOT NULL, mailbox_id uuid NOT NULL,
    UNIQUE(tenant_id,mailbox_id)
);
CREATE TABLE IF NOT EXISTS ledger_acl (
    scope_ref uuid NOT NULL REFERENCES ledger_scopes, db_role name NOT NULL,
    PRIMARY KEY(scope_ref,db_role)
);
CREATE TABLE IF NOT EXISTS ledger_issuers (
    scope_ref uuid NOT NULL REFERENCES ledger_scopes, issuer_ref uuid NOT NULL,
    client_id uuid NOT NULL, subject_id uuid NOT NULL,
    kinds text[] NOT NULL CHECK(cardinality(kinds)>0 AND kinds <@ ARRAY['send_execution','generation','content_inclusion','content_edit','copy_mapping']::text[]),
    enrolled_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(scope_ref,issuer_ref)
);
CREATE TABLE IF NOT EXISTS ledger_keys (
    scope_ref uuid NOT NULL, issuer_ref uuid NOT NULL, key_ref uuid NOT NULL,
    public_key bytea NOT NULL CHECK(octet_length(public_key)=32),
    valid_from timestamptz NOT NULL, valid_until timestamptz NOT NULL CHECK(valid_until>valid_from),
    PRIMARY KEY(scope_ref,issuer_ref,key_ref),
    FOREIGN KEY(scope_ref,issuer_ref) REFERENCES ledger_issuers
);
CREATE TABLE IF NOT EXISTS ledger_observers (
    scope_ref uuid NOT NULL REFERENCES ledger_scopes, source_ref uuid NOT NULL,
    namespace text NOT NULL CHECK(namespace IN ('graph_immutable','exchange_store','external_source')),
    source_schema_version text NOT NULL,
    capture_basis text NOT NULL CHECK(capture_basis IN ('synthetic_fixture','committed_ingestion')),
    PRIMARY KEY(scope_ref,source_ref)
);
CREATE TABLE IF NOT EXISTS ledger_revocations (
    revocation_ref uuid PRIMARY KEY, scope_ref uuid NOT NULL, issuer_ref uuid NOT NULL,
    key_ref uuid, recorded_at timestamptz NOT NULL DEFAULT now(),
    reason text NOT NULL CHECK(reason IN ('compromise','retired','owner_withdrawal')),
    FOREIGN KEY(scope_ref,issuer_ref) REFERENCES ledger_issuers
);
CREATE TABLE IF NOT EXISTS ledger_messages (
    scope_ref uuid NOT NULL REFERENCES ledger_scopes, message_ref uuid NOT NULL, version_ref uuid NOT NULL,
    source_ref uuid NOT NULL, source_event_ref uuid NOT NULL, source_schema_version text NOT NULL CHECK(source_schema_version ~ '^[a-zA-Z0-9][a-zA-Z0-9_./-]{0,63}$'),
    namespace text NOT NULL CHECK(namespace IN ('graph_immutable','exchange_store','external_source')),
    immutable_digest text NOT NULL CHECK(immutable_digest ~ '^[a-f0-9]{64}$'),
    internet_digest text CHECK(internet_digest ~ '^[a-f0-9]{64}$'),
    copy_role text NOT NULL CHECK(copy_role IN ('sender','recipient','unknown')),
    message_state text NOT NULL CHECK(message_state IN ('draft','sent','received','unknown')),
    observed_at timestamptz NOT NULL, source_event_at timestamptz, recorded_at timestamptz NOT NULL DEFAULT now(), sent_at timestamptz,
    material_cipher bytea NOT NULL, material_digest text NOT NULL CHECK(material_digest ~ '^[a-f0-9]{64}$'),
    expires_at timestamptz NOT NULL DEFAULT now()+interval '7 days',
    CHECK(expires_at<=recorded_at+interval '7 days'),
    PRIMARY KEY(scope_ref,message_ref,version_ref),
    UNIQUE(scope_ref,source_ref,source_event_ref),
    FOREIGN KEY(scope_ref,source_ref) REFERENCES ledger_observers
);
CREATE TABLE IF NOT EXISTS ledger_receipts (
    evidence_ref uuid PRIMARY KEY, scope_ref uuid NOT NULL, issuer_ref uuid NOT NULL, key_ref uuid NOT NULL,
    event_id uuid NOT NULL, message_ref uuid NOT NULL, version_ref uuid NOT NULL,
    kind text NOT NULL CHECK(kind IN ('send_execution','generation','content_inclusion','content_edit','copy_mapping')),
    record_digest text NOT NULL CHECK(record_digest ~ '^[a-f0-9]{64}$'),
    envelope_cipher bytea NOT NULL,
    received_at timestamptz NOT NULL DEFAULT now(), expires_at timestamptz NOT NULL,
    CHECK(expires_at<=received_at+interval '7 days'),
    UNIQUE(scope_ref,issuer_ref,event_id),
    UNIQUE(scope_ref,evidence_ref),
    FOREIGN KEY(scope_ref,issuer_ref,key_ref) REFERENCES ledger_keys,
    FOREIGN KEY(scope_ref,message_ref,version_ref) REFERENCES ledger_messages
);
ALTER TABLE ledger_messages ADD COLUMN IF NOT EXISTS source_event_at timestamptz;
CREATE TABLE IF NOT EXISTS ledger_conflicts (
    conflict_ref uuid PRIMARY KEY, scope_ref uuid NOT NULL, evidence_ref uuid NOT NULL,
    conflicting_digest text NOT NULL CHECK(conflicting_digest ~ '^[a-f0-9]{64}$'),
    recorded_at timestamptz NOT NULL DEFAULT now(), expires_at timestamptz NOT NULL DEFAULT now()+interval '7 days',
    CHECK(expires_at<=recorded_at+interval '7 days'), UNIQUE(scope_ref,evidence_ref,conflicting_digest),
    FOREIGN KEY(scope_ref,evidence_ref) REFERENCES ledger_receipts(scope_ref,evidence_ref)
);
CREATE TABLE IF NOT EXISTS ledger_inputs (
    input_ref uuid PRIMARY KEY, scope_ref uuid NOT NULL, message_ref uuid NOT NULL, version_ref uuid NOT NULL,
    schema_version text NOT NULL CHECK(schema_version='1.0'),
    rule_version text NOT NULL CHECK(rule_version='correlation-v1'),
    revision integer NOT NULL CHECK(revision>0),
    prior_input_ref uuid,
    view_cipher bytea NOT NULL, view_digest text NOT NULL CHECK(view_digest ~ '^[a-f0-9]{64}$'),
    recorded_at timestamptz NOT NULL DEFAULT now(), expires_at timestamptz NOT NULL DEFAULT now()+interval '30 days',
    CHECK(expires_at<=recorded_at+interval '30 days'),
    FOREIGN KEY(scope_ref) REFERENCES ledger_scopes
);
-- Also upgrade an empty development preview without dropping any stored records.
ALTER TABLE ledger_inputs ADD COLUMN IF NOT EXISTS revision integer NOT NULL DEFAULT 1 CHECK(revision>0);
ALTER TABLE ledger_inputs ALTER COLUMN revision DROP DEFAULT;
CREATE UNIQUE INDEX IF NOT EXISTS ledger_input_revisions ON ledger_inputs(scope_ref,message_ref,revision);
CREATE INDEX IF NOT EXISTS ledger_receipts_message ON ledger_receipts(scope_ref,message_ref,version_ref);
CREATE INDEX IF NOT EXISTS ledger_inputs_message ON ledger_inputs(scope_ref,message_ref,recorded_at);
CREATE OR REPLACE FUNCTION ledger_input_binding() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NOT EXISTS(SELECT 1 FROM ledger_messages WHERE scope_ref=NEW.scope_ref AND message_ref=NEW.message_ref AND version_ref=NEW.version_ref AND expires_at>now()) THEN
        RAISE EXCEPTION 'ledger_input_message_binding_required';
    END IF;
    IF NEW.prior_input_ref IS NOT NULL AND NOT EXISTS(SELECT 1 FROM ledger_inputs WHERE input_ref=NEW.prior_input_ref AND scope_ref=NEW.scope_ref AND message_ref=NEW.message_ref AND expires_at>now()) THEN
        RAISE EXCEPTION 'ledger_prior_input_binding_required';
    END IF;
    RETURN NEW;
END $$;
CREATE OR REPLACE TRIGGER ledger_input_scoped BEFORE INSERT ON ledger_inputs FOR EACH ROW EXECUTE FUNCTION ledger_input_binding();

-- Guard even accidental owner-level UPDATE/TRUNCATE. The migration owner remains a
-- privileged trust boundary: it can explicitly change DDL; this is not WORM storage.
CREATE OR REPLACE FUNCTION ledger_append_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP='DELETE' AND OLD.expires_at<=now() AND pg_has_role(current_user,'agenttrace','USAGE') THEN
        RETURN OLD;
    END IF;
    RAISE EXCEPTION 'ledger_append_only';
END $$;
CREATE OR REPLACE FUNCTION ledger_config_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'ledger_configuration_append_only'; END $$;
DO $$
DECLARE item text;
BEGIN
    FOREACH item IN ARRAY ARRAY['ledger_messages','ledger_receipts','ledger_conflicts','ledger_inputs'] LOOP
        EXECUTE format('CREATE OR REPLACE TRIGGER ledger_no_rewrite BEFORE UPDATE OR DELETE ON %I FOR EACH ROW EXECUTE FUNCTION ledger_append_guard()',item);
        EXECUTE format('CREATE OR REPLACE TRIGGER ledger_no_truncate BEFORE TRUNCATE ON %I FOR EACH STATEMENT EXECUTE FUNCTION ledger_config_guard()',item);
    END LOOP;
    FOREACH item IN ARRAY ARRAY['ledger_scopes','ledger_issuers','ledger_keys','ledger_revocations','ledger_observers'] LOOP
        EXECUTE format('CREATE OR REPLACE TRIGGER ledger_config_no_rewrite BEFORE UPDATE OR DELETE OR TRUNCATE ON %I FOR EACH STATEMENT EXECUTE FUNCTION ledger_config_guard()',item);
    END LOOP;
END $$;
