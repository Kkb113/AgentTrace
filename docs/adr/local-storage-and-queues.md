# Local persistence and development queues

Status: implemented and tested with PostgreSQL 17.11.

Use digest-pinned PostgreSQL locally. The development adapter implements separate agent-evidence and content-analysis queues with transactional claims, visibility deadlines, receipt validation, retries, explicit poison state and payload-aware idempotency. Result persistence and acknowledgement share a database transaction. Concurrent receivers use row locking with SKIP LOCKED. Tests use independently created disposable schemas. Stop preserves local volumes.

This adapter is not an Azure Storage Queue emulator. Azure delivery/pop-receipt renewal, visibility limits, poison movement, recovery and database idempotency must be tested against the actual Azure queue in the later ingestion CI. PostgreSQL local tests cannot qualify cloud parity.

The API and database publish only to 127.0.0.1. A separate local-access bridge enables Docker Desktop port forwarding; attribution/content workers use only the internal network. All data is synthetic. The API is deliberately unauthenticated only in this loopback foundation and rejects a production environment. Production identity, TLS, network isolation, private endpoints and database role separation remain mandatory before deployment.
