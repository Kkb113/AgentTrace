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

The integration command creates a local migration password, distinct API/attribution/content/collector passwords and a fictional development signing key under ignored work/local. It builds the pinned image, configures SQL grants/row security, starts PostgreSQL/API/two workers and runs real database plus authenticated TCP tests. Each runtime service receives only its own database secret; the API receives public verification material, never the signing private key. On POSIX the host secret directory is owner-only; individually mounted secret files are readable by the unprivileged container UID. On Windows use the operator ACL helper in the secure-access runbook. These are local test credentials, not Entra credentials. API/database bind to 127.0.0.1:8080 and 127.0.0.1:55432. Workers have no host ports.

Health: GET http://127.0.0.1:8080/health/ready reports database, authorization and worker readiness plus the model-not-installed state. Enqueue the authored reference with docker compose run --rm --no-deps collector-tools enqueue-example. GET /v1/decisions/{id} requires a correctly signed development access token and enrolled message entitlement; unauthenticated calls return 401. The integration harness mints short-lived tokens in memory from the ignored test key. It verifies the full round trip and token/role/tenant/expiry rejections without printing tokens. The fixture result is not live-source accuracy evidence. No email is sent.

Stop with uv run python scripts/dev-services.py stop; database volumes are retained. The helper can target only agenttrace-foundation or agenttrace-foundation-clean. For a second clean-checkout run, stop the original stack, use --project agenttrace-foundation-clean, and set AGENTTRACE_COMPOSE_PROJECT to that exact name for end-to-end tests. Never reuse a different checkout's password with an existing database volume. Never remove unrelated Docker volumes.

Changing dependencies requires uv lock, uv sync --frozen --all-groups and python scripts/export-locks.py. Changing contracts requires python scripts/export-contracts.py. CI rejects stale exports, invalid contracts, failed tests, synthetic credential findings, unknown licenses and unreviewed public identifiers. Negative-gate controls intentionally invoke failing subprocesses and succeed only when each subprocess exits 1.
