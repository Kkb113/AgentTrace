# Graph activity implementation review

Status: configuration verified and software validation passed; live request delivery
is pending. The source must not be represented as end-to-end validated until
`graph-activity-live-validation.json` records the fresh request traces and durable
ingestion. Empty results remain pending rather than proof of human sending.

The actual preflight confirmed existing tenant P1/P2 service plans, the operator's
assigned P1 entitlement and active Global Administrator role. The new dedicated
East US pay-as-you-go workspace and transformation rule are in `kb-agentdemo`.
Graph retention is seven days, the daily ingestion safeguard is 0.1 GB, and no
standing compute, commitment tier, Sentinel or purchased license was added.

The deployed transformation passed positive/negative synthetic cases in Azure's KQL
engine. It retains only the enrolled application/user contexts and strips URL query
strings. The conditional table role was read back. Actual content/API identities were
denied query access. The permitted collector GET succeeded and the control-mailbox
GET was denied. Tenant settings, shared workspaces and existing evidence firewalls
were preserved.

The operator prepared a fresh Claude send externally. No AgentTrace operation sent
or moved email. Exact control request IDs are retained privately for live correlation;
earlier batches remain visible when fresh probes are generated. An empty non-target
table is distinguished from an explicit access denial. Source export remains
tenant-wide before downstream minimization.

Local validation passed all five gates: 216 unit/security tests, 52 subtests and 62
integration/end-to-end tests. The added tests cover send-versus-draft/read/move
semantics, failure statuses, URI redaction, delayed arrivals, deduplication, empty
initial delivery, throttling, malformed/partial results and transaction rollback.
The deployment guard preserves the DCR attachment on repeat setup and refuses changes
to unrelated shared resources. The repeat plan changed only a provider-populated
table schema default, with three NoChange resources and thirteen ignored resources.

[Design, costs and runbook](graph-activity-logging.md),
[live evidence](evidence/graph-activity-live-validation.json),
[software evidence](evidence/graph-activity-validation.json).

API activity is evidence for later message-specific correlation. It does not prove
AI execution or generated wording, and no detection-accuracy qualification is claimed.
