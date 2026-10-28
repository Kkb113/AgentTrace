# Microsoft Graph activity logging

Review date: 29 October 2026, Asia/Calcutta. This extends the read-only detection
platform with application/API-request evidence. It does not add email execution or
make an API call sufficient proof of AI-agent sending.

## Deployment and licensing

The operator's actual tenant license inventory includes enabled Entra ID P1/P2
service plans, and the operator has an assigned P1 entitlement. The active Global
Administrator role and successful tenant diagnostic-setting operation establish the
setup access used. No license was purchased and no new Microsoft 365 send/write or
mailbox-read permission was granted. The existing separate audit collector's
certificate identity receives Azure query access for this stream.

The existing East US workspace is shared and was left unchanged. A dedicated
pay-as-you-go `PerGB2018` workspace and workspace-transformation data collection
rule are created in `kb-agentdemo`, East US. There is no commitment tier, Sentinel,
VM, hosted database, GPU or always-on Azure compute. The Graph table uses the
Analytics plan with seven-day analytics and total retention. The workspace's
thirty-day default applies to service bookkeeping tables, not this Graph table.
Basic's fixed thirty-day query retention does not fit the agreed seven-day raw
evidence boundary. [Table retention](https://learn.microsoft.com/en-us/azure/azure-monitor/logs/data-retention-configure).

Entra's `MicrosoftGraphActivityLogs` diagnostic setting is necessarily tenant-scoped;
its billable destination and DCR are in the requested resource group. Only that log
category is enabled in the dedicated setting. Other tenant diagnostic settings,
shared workspaces, original evidence storage and Key Vault are preserved.

## Data scope and permissions

Microsoft's export covers the tenant's Graph requests. Diagnostic settings cannot
apply a mailbox/app filter. Before storage, the workspace transformation keeps only:

- Requests for the enrolled pilot user through the explicitly enrolled Claude
  connector application.
- Requests by the existing AgentTrace mailbox/audit collector application IDs,
  including app-only requests with no user ID, for positive/negative access auditing.

Other users/apps/tenants are discarded by the transformation. This is downstream
minimization, not a narrower tenant export permission. Unknown apps, other users,
external tenants and protocols that do not traverse Microsoft Graph are outside
this POC activity-source coverage. Enrolling another application is an explicit
scope change, not an automatic AI classification.

Stored fields are request time, tenant/app/user identifiers, request/client-request
identifiers, method, query-free request URI and response status. URL query strings
are removed before storage; the collector independently removes queries/fragments
before encrypting its local envelope. IP addresses, token claims, scopes and user
agent strings are omitted. Email bodies and API request/response bodies are not
collected by this adapter. Remaining identifiers and URI paths are still sensitive.
[Microsoft's schema and export limits](https://learn.microsoft.com/en-us/graph/microsoft-graph-activity-logs-overview).

The certificate reader uses the documented Log Analytics token audience and the
current `api.loganalytics.azure.com` endpoint. Its Log Analytics Data Reader role is
assigned only at the dedicated workspace with an ABAC condition naming the Graph
table. The built-in role's General-table condition also applies. There is no role
grant on the shared workspace. Content and detection API identities have no activity
query role. An HTTP 200 empty result is recorded distinctly from a 403; empty-table
results alone cannot demonstrate cross-table data denial. Actual conditional role
readback and actual wrong-identity tests are recorded in the live validation report.
[Granular RBAC](https://learn.microsoft.com/en-us/azure/azure-monitor/logs/granular-rbac-use-case).

## Collection and interpretation

The collector overlaps the previous event-time watermark by 24 hours and waits five
minutes behind current time. Microsoft commonly delivers logs within about thirty
minutes, with less common delays up to two hours; the overlap is intended to recover
delayed arrivals. It is a finite replay
horizon, not a guarantee that every arbitrarily late event is collected. Current
means the bounded query window was observed successfully, not that all provider
events have arrived. Initial empty delivery stays `catching_up` with a pending reason.
Historical pre-enable gaps remain unrecoverable with unknown lost counts.

At most 10,000 rows are accepted in a query window. Overflow, partial results,
malformed rows, unexpected applications, access errors and throttling fail the whole
window without partial writes or a watermark advance. Overflow requires an operator
to narrow/split the window; it must never be silently truncated. Checkpoint receipts
fence concurrent workers. Request IDs deduplicate overlapping ingestion. Source and
ingestion times remain separate; encrypted local records expire at seven days.

Successful `POST` calls to the supported mail `sendMail`, message `send`, `reply`,
`replyAll` and `forward` routes are **send-request observations** for correlation.
Draft creation, edits, reads, moves and failed sends do not qualify. Collector actions
are retained for auditing and excluded from attribution signals. A 202 response is
not proof of completed delivery. A known application/API operation still needs
message-specific evidence and an appropriate trust rule before an AI-agent verdict.
Statistical AI-content detection remains independent and is not implemented by logs.

## Cost controls

The retrieved East US paid Analytics ingestion meter is USD 2.30/GB; no free grant is
assumed. An illustrative 10 MB/day of retained log data would cost about USD 0.69 per
30-day month for ingestion alone. Actual invoices depend on volume, subscription
terms, filtering/processing and other applicable charges. Filtering more than half
the incoming data can incur a separate processing charge; the raw tenant feed can
therefore cost money even when few rows are retained. No hard monthly bill ceiling
is claimed. [Retail Prices API](https://learn.microsoft.com/en-us/rest/api/cost-management/retail-prices/azure-retail-prices),
[transformation costs](https://learn.microsoft.com/en-us/azure/azure-monitor/logs/cost-logs).

A 0.1 GB/day workspace ingestion cap is a secondary safeguard. It is evaluated after
transformation, can overshoot and can stop collection. It does not cap all upstream
processing costs or guarantee a dollar limit. Avoid using it as routine filtering;
if reached, record a coverage gap and investigate rather than infer no agent activity.
No chargeable alert rule or email notification was added. Review the workspace usage
and cap state during the POC. [Daily cap behavior](https://learn.microsoft.com/en-us/azure/azure-monitor/logs/daily-cap).

## Operations and validation

1. Run `python scripts/inspect-graph-activity.py` using the already authenticated
   operator session. Raw license/role/settings inventories stay in `work/private`.
2. Compile Bicep using `python scripts/validate-infrastructure.py`. Review
   `python scripts/configure-graph-activity.py` before using `--apply`. Defaults
   provision nothing. The guarded what-if rejects deletion, out-of-group resources
   and modifications of unrelated shared resources. A repeat setup preserves an
   existing DCR attachment and original enable timestamp.
3. `python scripts/prepare-graph-activity.py` enrolls the source, preserves an active
   watermark and retires the old unconfigured partition. `collect-audit-evidence.py`
   no longer marks this configured source unavailable; legacy Office Activity remains off.
4. Run `python scripts/collect-graph-activity.py` for one cycle, or add `--watch` for
   supervised local collection every five minutes. Stopping the local reader does
   not stop Microsoft's cloud log export. Existing retention maintenance still applies.
5. `python scripts/probe-graph-activity.py` issues only uniquely traceable GETs: an
   allowed synthetic-folder read, an expected denied control-mailbox read and an
   excluded application. No probe sends mail. Agent-send smoke messages are prepared
   externally by the operator in Claude.
6. `python scripts/verify-graph-activity.py` checks actual configuration, data traces,
   scope/redaction cases in Azure's KQL engine, wrong-identity denials and encrypted
   durable ingestion. Pending/absent records cannot satisfy live exits. Query IDs,
   raw responses, source records and credentials are never published. See
   [the live report](evidence/graph-activity-live-validation.json).

To stop further export, an authorized operator can disable only the
`AgentTraceGraphActivity` setting in Entra diagnostic settings after checking that
its workspace matches this project's private configuration. Mark the local source
disabled and record the stopped interval. Existing data ages out under its table
retention policy; disabling export does not retroactively delete it. Never delete
the shared resource group or modify other settings as cleanup. Private test captures
must be handled under the seven-day evidence policy; preserve active configuration
and credentials separately from expiring captures.
