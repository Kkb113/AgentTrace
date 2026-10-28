CREATE TABLE IF NOT EXISTS foundation_schema (
    version integer PRIMARY KEY CHECK (version = 1)
);
INSERT INTO foundation_schema(version) VALUES (1) ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS detection_jobs (
    job_id uuid PRIMARY KEY,
    queue_name text NOT NULL CHECK (queue_name IN ('agent-evidence', 'content-analysis')),
    idempotency_key text NOT NULL,
    payload jsonb NOT NULL,
    state text NOT NULL DEFAULT 'pending' CHECK (state IN ('pending', 'completed', 'poison')),
    visible_at timestamptz NOT NULL,
    attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    receipt uuid,
    last_error_code text,
    UNIQUE(queue_name, idempotency_key)
);
CREATE INDEX IF NOT EXISTS detection_jobs_visible
    ON detection_jobs(queue_name, visible_at) WHERE state = 'pending';

CREATE TABLE IF NOT EXISTS detection_decisions (
    decision_id uuid PRIMARY KEY,
    job_id uuid NOT NULL UNIQUE REFERENCES detection_jobs(job_id),
    decision jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL DEFAULT now() + interval '30 days',
    CHECK (decision ? 'findings'),
    CHECK (jsonb_typeof(decision->'findings') = 'object'),
    CHECK (((decision->'findings') - 'agent_send_attribution' - 'content_assessment') = '{}'::jsonb),
    CHECK ((decision->'findings') ? 'agent_send_attribution'),
    CHECK ((decision->'findings') ? 'content_assessment')
);

CREATE TABLE IF NOT EXISTS component_health (
    component text PRIMARY KEY CHECK(component IN ('attribution', 'content')),
    observed_at timestamptz NOT NULL
);

-- These checks also upgrade the existing local foundation volume. They prevent a
-- direct producer SQL connection from storing bodies or extending decision retention.
DO $migration$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='detection_jobs'::regclass AND conname='reference_only_job_payload') THEN
        ALTER TABLE detection_jobs ADD CONSTRAINT reference_only_job_payload CHECK (
            jsonb_typeof(payload)='object'
            AND (payload-'schema_version'-'fixture_ref'-'message_ref')='{}'::jsonb
            AND payload ?& ARRAY['schema_version','fixture_ref','message_ref']
            AND jsonb_typeof(payload->'schema_version')='string'
            AND jsonb_typeof(payload->'fixture_ref')='string'
            AND jsonb_typeof(payload->'message_ref')='string'
            AND payload->>'schema_version'='1.0'
            AND payload->>'fixture_ref'='authored_contract_example'
            AND length(payload->>'message_ref') BETWEEN 1 AND 256
        );
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='detection_decisions'::regclass AND conname='bounded_decision_retention') THEN
        ALTER TABLE detection_decisions ADD CONSTRAINT bounded_decision_retention
            CHECK (expires_at<=created_at+interval '30 days');
    END IF;
END
$migration$;
