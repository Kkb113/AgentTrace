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
