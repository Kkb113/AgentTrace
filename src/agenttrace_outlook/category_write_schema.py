"""Decision-bound durable category intents and before-send receipts in the runtime DB."""

CATEGORY_WRITE_SCHEMA = (
    "CREATE TABLE category_intents (id INTEGER PRIMARY KEY, decision_id INTEGER NOT NULL UNIQUE REFERENCES decisions(id) ON DELETE CASCADE, message_id TEXT NOT NULL REFERENCES messages(message_id), status TEXT NOT NULL CHECK(status IN ('pending','prepared','uncertain','applied','unchanged','reconciled','superseded','blocked','rollback_pending','rolled_back','rollback_blocked')), attempts INTEGER NOT NULL DEFAULT 0, due REAL NOT NULL DEFAULT 0, error_code TEXT, created REAL NOT NULL, updated REAL NOT NULL)",
    "CREATE TABLE category_attempts (id INTEGER PRIMARY KEY, intent_id INTEGER NOT NULL REFERENCES category_intents(id) ON DELETE CASCADE, operation TEXT NOT NULL CHECK(operation IN ('apply','rollback')), status TEXT NOT NULL CHECK(status IN ('prepared','uncertain','confirmed','conflict','rejected','reconciled')), payload TEXT NOT NULL, created REAL NOT NULL)",
    "CREATE INDEX category_intents_due ON category_intents(status,due)",
)
