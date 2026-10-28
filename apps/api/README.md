# API host

The runnable FastAPI host is `agenttrace_foundation.api`. Run `agenttrace-foundation api` on loopback or use Compose. GET health and synthetic decision queries are the only routes. Decisions require validated access tokens, roles and server-owned message entitlements. Compose uses fictional local signing material; the live verification harness also exercises actual Entra-issued tokens. The API has a read-only SQL login and no mailbox/signing/queue-execution permission. Continuous ingestion and production rollout remain later milestones; this host refuses a production environment.
