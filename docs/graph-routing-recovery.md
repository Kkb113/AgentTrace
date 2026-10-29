# Graph activity delivery investigation

Review date: 29 October 2026, Asia/Calcutta. Graph event delivery remains unresolved.
The work below improves diagnosis and performs one bounded recovery attempt; it
does not establish an AI-agent verdict or a recovered Graph feed.

## What was tested

| Component | Actual result | Meaning |
| --- | --- | --- |
| Tenant and license | Matching workforce tenant and existing premium entitlement | No evidence of a wrong tenant/B2C route or a missing purchased license |
| Graph controls | Authorized synthetic-folder GET succeeds; control-mailbox and directory GETs return expected 403 | Confirmed requests and exact request IDs are available for source correlation |
| Workspace canary | Ingestion returns 204; the exact synthetic record is returned once | Direct ingestion and query work for the canary path in the target workspace |
| Canary authorization | Operator has Monitoring Metrics Publisher only on the canary DCR | No Microsoft 365 permission or product-worker permission was added |
| Graph DCR metrics | No actual measurement samples | Input volume is unknown; missing samples must not be reported as measured zero |
| Operational error logging | Enabled on the dedicated DCR; error text reduced to fixed buckets before storage | Future processing failures can be observed without retaining raw error messages |
| Route refresh | One disable/restore sequence, independently verified enabled afterward | Other tenant settings were preserved; a 16.19-second unknown-loss interval is recorded |
| Graph records | No source records observed at the latest check | Graph-specific publishing/routing, filtering and table-specific authorization remain unproven |
| Independent latest-Claude check | `verified_agent` from one authenticated successful Exchange Send event and a unique exact Internet Message-ID match | The enrolled Claude attribution route works without Graph activity-log records; this is one test, not a coverage/accuracy qualification |
| Independent native archive | No objects/matching controls in a ten-minute foreground observation; temporary export confirmed stopped afterward | Inconclusive: neither source activation nor the alternate delivery path is qualified by this observation |

The canary uses `AgentTraceRouteCanary_CL`, with only a random canary ID, timestamp
and fixed test label. It uses a separate direct-ingestion DCR, not the Graph export
publisher. Both that table and the redacted `DCRLogErrors` table retain seven days.
The existing 0.1 GB/day ingestion safeguard covers the workspace; it remains neither
a hard bill ceiling nor a cap on upstream processing costs. No standing compute,
new license, secret or Microsoft 365 send/write grant was introduced.

The operator's canary initially received 403 without the publish data action. A
rule-scoped grant and propagation resolved that test issue. It was not established
as the cause of the original Graph-feed problem. Microsoft documents up to thirty
minutes for this permission to propagate. [Ingestion API troubleshooting](https://github.com/Azure/azure-sdk-for-python/blob/main/sdk/monitor/azure-monitor-ingestion/TROUBLESHOOTING.md).

Modern table/authorization API readbacks did not report a protection level or data
authorization mode. Do not assume those fields prove access or weaken table protection
to make data visible. Empty results can reflect authorization as well as absent
delivery. [Protected-table behavior](https://learn.microsoft.com/en-us/azure/azure-monitor/logs/protected-tables-configure).

## Reproduce the diagnosis

1. Run `python scripts/diagnose-graph-activity.py --probe` for read-only controls,
   tenant checks, sample-aware DCR metrics and redacted error counts. Actual request
   IDs and raw responses stay in the protected private directory.
2. `python scripts/test-graph-route.py` previews the synthetic canary deployment.
   `--apply` publishes one synthetic record and verifies its exact query result.
   It creates a dedicated table/DCR and an operator-only, DCR-scoped publisher grant.
   A 204 acknowledgment alone does not pass the test; a returned matching row is required.
3. Inspect `docs/evidence/graph-route-canary-validation.json`,
   `graph-activity-diagnostics.json` and `graph-route-refresh-validation.json`.
   They distinguish a functioning destination from an unverified Graph publisher.
4. `python scripts/verify-graph-activity.py` remains the complete Graph-source gate.
   It must observe the real allowed/denied requests and encrypted durable ingestion,
   not merely a working custom canary table.

`scripts/refresh-graph-diagnostic-route.py` defaults to preview, requires a passed
destination canary before applying, validates the managed destination and refuses
routes with other active categories or destinations. It preserves provider-expanded
disabled categories. It records an attempt before changing the route and refuses
repeated toggles. Azure returned 404 while the fully disabled setting was absent;
the finally block restored the original enabled route. Saved successful API receipts
and an independent live readback were reconciled with `--record-recovery`; no second
toggle was used. This behavior is captured explicitly rather than hiding the error.

## Recovery and escalation

Normal Graph event latency and first diagnostic activation are different. Microsoft
describes normal delivery within thirty minutes, with some events taking two hours,
while Entra setup guidance allows up to three days before a new diagnostic stream
starts appearing. A routing refresh does not guarantee or shorten activation. Keep
the original enable time and the refresh time, preserve unknown coverage, and do not
repeatedly recreate settings. [Graph latency](https://learn.microsoft.com/en-us/graph/microsoft-graph-activity-logs-overview),
[Entra startup guidance](https://learn.microsoft.com/en-us/entra/identity/monitoring-health/howto-configure-diagnostic-settings#basic-process).

If records remain absent, use `python scripts/build-graph-support-pack.py` to prepare
an operator-private Microsoft support note with exact tenant/resource/request
references and executed checks. It sends nothing. Ask Microsoft to verify category
provisioning, resource-tenant emission, diagnostic routing and table authorization.
Do not claim a confirmed Microsoft outage from these observations or buy a support
plan/license as an automatic remedy.

A second destination such as Blob Storage can further separate tenant emission
from Log Analytics delivery. Native archival cannot apply the workspace's pilot/app
filter before storage, and could retain full tenant request URIs, query strings, IPs,
identity and token identifiers. The user accepted that isolated data-handling and
network exception on 29 October 2026; see the
[reviewed proposal](graph-route-isolation-proposal.md). It is a temporary diagnostic,
not an expanded product collection policy. Its executed results and confirmed stopped
state belong in `evidence/graph-archive-diagnostic-validation.json`.
[Supported destinations and source limits](https://learn.microsoft.com/en-us/graph/microsoft-graph-activity-logs-overview).

The approved test actually ran from 05:24 to 05:34 UTC on 29 October. The new account's
storage/network/retention controls and operator-only container grant were read back,
and its Entra export was enabled. No archive objects or exact control IDs were
observed during the bounded test. The temporary export was then independently
confirmed stopped and all other tenant settings preserved. Shared-key access stayed
disabled. This does not establish native writer/authentication compatibility or prove
a source-emission fault; no actual delivery occurred to qualify that route. Ask
Microsoft to check native archive authorization as well as category provisioning.
The inactive diagnostic account is retained under the approved lifecycle policy;
no resources were deleted and no longer capture interval was started.

For a later explicitly authorized repeat, `python scripts/test-graph-archive.py`
previews the managed resources; `--apply --wait-seconds 600` requires a matching
recorded proposal acceptance. `--stop` stops only its saved dedicated route. It
neither changes the original Graph workspace route nor enables other categories.

For the platform, retain authenticated Exchange Send audit evidence as the primary
supported path while Graph is pending. In addition to the earlier feasibility test,
`python scripts/verify-agent-audit-fallback.py` freshly authenticated and correlated
the owner's fixed `AT-GRAPH-ACTIVITY-01` synthetic email. It returned `verified_agent`
only after a successful Exchange Send event matched the authenticated tenant/mailbox,
the publisher-verified enrolled Claude application and a unique exact Internet
Message-ID. The bounded four-minute audit search completed; a transient GET failure
was recovered by `--resume`, without creating another search. Resume verifies the
saved search window, operation and principal filters, normalizing Microsoft's date
format and enum capitalization. No mailbox write or new permission was needed.

The observation age is an upper bound on availability, not measured source ingestion
latency or a real-time service claim. This separately demonstrated message does not
establish general application coverage, false-positive rates or generated content.
The audit/store-to-Graph immutable-ID equivalence remains unproven. Missing Graph
evidence stays unknown and does not establish a human sender.

## Evidence

- [Current diagnostics](evidence/graph-activity-diagnostics.json)
- [Workspace canary](evidence/graph-route-canary-validation.json)
- [Recorded route refresh](evidence/graph-route-refresh-validation.json)
- [Accepted archive diagnostic scope](evidence/graph-archive-diagnostic-acceptance.json)
- [Archive diagnostic result](evidence/graph-archive-diagnostic-validation.json)
- [Fresh independent Exchange attribution](evidence/agent-audit-fallback-validation.json)
- [Complete Graph-source gate](evidence/graph-activity-live-validation.json)
