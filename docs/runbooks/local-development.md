# Start and validate the local foundation

Prerequisites: Python 3.12.14, uv 0.12.12, Git, and a running Docker engine with Compose. No Azure login or mailbox grant is needed.

From the repository root:

```powershell
uv sync --frozen --all-groups
uv run python scripts/bootstrap-tools.py all
uv run python scripts/ci-checks.py quality
uv run python scripts/ci-checks.py security
uv run python scripts/ci-checks.py infrastructure
uv run python scripts/ci-checks.py guard-controls
uv run python scripts/ci-checks.py integration
```

The integration command creates a random local database password in ignored work/local, builds the pinned image, starts PostgreSQL/API/two workers and runs real database plus TCP round-trip tests. On POSIX the host secret directory is owner-only; the file is readable through a read-only container secret mount by the unprivileged application UID. Windows uses the workspace ACL. These are generated local test credentials, not tenant credentials. The API and database bind to 127.0.0.1:8080 and 127.0.0.1:55432. Workers have no host ports.

Health: GET http://127.0.0.1:8080/health/ready reports database and worker freshness plus the explicit model-not-installed state. Enqueue only the authored reference with agenttrace-foundation enqueue-example; query its returned decision ID through GET /v1/decisions/{id}. The fixture result is not live-source accuracy evidence. No email is sent.

Stop with uv run python scripts/dev-services.py stop; database volumes are retained. The helper can target only agenttrace-foundation or agenttrace-foundation-clean. For a second clean-checkout run, stop the original stack, use --project agenttrace-foundation-clean, and set AGENTTRACE_COMPOSE_PROJECT to that exact name for end-to-end tests. Never reuse a different checkout's password with an existing database volume. Never remove unrelated Docker volumes.

Changing dependencies requires uv lock, uv sync --frozen --all-groups and python scripts/export-locks.py. Changing contracts requires python scripts/export-contracts.py. CI rejects stale exports, invalid contracts, failed tests, synthetic credential findings, unknown licenses and unreviewed public identifiers. Negative-gate controls intentionally invoke failing subprocesses and succeed only when each subprocess exits 1.
