"""Additive schema v2; upgraded atomically after verifying the exact v1 structure."""

SYNC_SCHEMA = (
    "CREATE TABLE sync_jobs (key TEXT PRIMARY KEY, kind TEXT NOT NULL, target TEXT NOT NULL, cursor TEXT, generation INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'due', due REAL NOT NULL DEFAULT 0, attempts INTEGER NOT NULL DEFAULT 0, error TEXT, epoch INTEGER NOT NULL DEFAULT 0, visited REAL NOT NULL DEFAULT 0)",
    "CREATE TABLE folders (id TEXT PRIMARY KEY, parent_id TEXT NOT NULL, excluded TEXT, seen_epoch INTEGER NOT NULL, active INTEGER NOT NULL DEFAULT 1)",
    "CREATE TABLE memberships (folder_id TEXT NOT NULL, message_id TEXT NOT NULL, present INTEGER NOT NULL, epoch INTEGER NOT NULL, PRIMARY KEY(folder_id,message_id))",
    "CREATE TABLE sync_items (message_id TEXT PRIMARY KEY, status TEXT NOT NULL, semantic_hash TEXT, provider_version TEXT, folder_id TEXT, first_seen REAL NOT NULL, expires REAL NOT NULL, revision INTEGER NOT NULL DEFAULT 0)",
    "CREATE TABLE snapshots (message_id TEXT PRIMARY KEY, payload TEXT NOT NULL, expires REAL NOT NULL)",
    "CREATE TABLE sync_gaps (id INTEGER PRIMARY KEY, job_key TEXT NOT NULL, code TEXT NOT NULL, created REAL NOT NULL, resolved INTEGER NOT NULL DEFAULT 0)",
    "CREATE INDEX sync_due ON sync_jobs(status,due,visited)",
)
