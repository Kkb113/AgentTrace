"""Durable source jobs, receipts and rule assessments; no mailbox writer."""

RULE_SCHEMA = (
    "CREATE TABLE rule_jobs (observation_id INTEGER PRIMARY KEY REFERENCES observations(id), stage TEXT NOT NULL DEFAULT 'new', query_id TEXT, cursor TEXT, due REAL NOT NULL DEFAULT 0, attempts INTEGER NOT NULL DEFAULT 0, generation INTEGER NOT NULL DEFAULT 0, records TEXT NOT NULL DEFAULT '[]', error TEXT)",
    "CREATE TABLE rule_sources (observation_id INTEGER PRIMARY KEY REFERENCES observations(id), payload TEXT NOT NULL, raw_payload TEXT NOT NULL, captured REAL NOT NULL, expires REAL NOT NULL)",
    "CREATE TABLE rule_assessments (observation_id INTEGER PRIMARY KEY REFERENCES observations(id), payload TEXT NOT NULL, assessed REAL NOT NULL)",
    "CREATE INDEX rule_jobs_due ON rule_jobs(stage,due)",
)
