# Secure sandbox data flow

**Baseline history:** This is the accepted 28 October dual-target Microsoft/Azure flow. The [Outlook-native revision](adr/outlook-native-categorization.md) defines the small production monitor and future scoped category-write exception. This flow is historical, not a new permission grant or implementation claim. Existing controls remain in force until explicitly migrated and tested.

Review state: accepted on 28 October 2026 by the user acting as project owner, Microsoft 365 administrator and security owner. Technical verification is recorded separately in the secure-access exit review.

1. The separate mailbox collector authenticates with its own workload certificate. Exchange authorizes only the enrolled mailbox. The adapter further restricts extraction to approved synthetic message references; it neither sends nor changes messages.
2. The separate audit collector authenticates with its Exchange-audit-only permission, submits tightly bounded Send searches and minimizes returned records before evidence use. It can technically query broader tenant Exchange records; query filters do not remove that residual exposure.
3. Raw synthetic captures stay in the protected raw-evidence container with a seven-day lifecycle and application expiry checks. Queue payloads carry validated references, not message bodies or tokens. Attribution and content queues have different role assignments.
4. The attribution worker reads the enrolled evidence, persists independent findings and uses the dedicated non-exportable signing key for digests. It cannot read Microsoft 365 or administer the key. Local PostgreSQL has separate application roles and minimal grants.
5. The content worker receives only a specifically authorized, current message version as transient input. It has no raw-container, Microsoft 365, history or signing credential and runs on the internal local network. No model is installed in this milestone. It reports unavailable/unknown, never a fabricated score, and cannot call a public detector.
6. The read-only API validates a token for its exact tenant and audience, then checks role, subject and server-side mailbox/message entitlement before fetching a decision. Collector permissions are never reused as a user's authorization. Selected-message add-in authorization will have its own independently verified entitlement when the add-in is implemented.
7. Decisions become inaccessible through the API and its SQL role after thirty days. Application raw-evidence reads reject expired references at seven days, independently of asynchronous storage lifecycle deletion. Azure Blob read roles themselves do not impose a timestamp condition; a compromised raw-reader credential remains a residual risk until physical deletion. Audit records contain event category, outcome and pseudonymous references only; tokens, certificates, body text, full request URLs and returned raw records are excluded from routine product logs. Azure service access diagnostics retain service-managed identity/network metadata within the existing protected workspace.

Azure Storage and Key Vault use dedicated resources in kb-agentdemo, East US, with Entra data-plane roles and operator-IP firewalls. The approved synthetic sandbox uses restricted public endpoints. Local services bind to loopback; content workers have an internal network without external access. No production deployment or Private Link claim is made.

Role/credential revocation, certificate overlap rotation, signing-key version retention, access-log inspection and safe resource suspension are documented in the access runbook. Do not delete the shared resource group or change another workload's resource configuration.


## Accepted notification transport addition

Graph basic notifications now enter through a dedicated East US Event Grid/Standard LRS metadata zone, then the local encrypted durable inbox and separate analysis dispatch. The owner accepted a trusted-services exception and destination-account delivery roles only on this new notification account after live validation rejected narrower scopes. The existing raw-evidence store and Key Vault remain unchanged. No new mailbox send/write grant exists. See [the ingestion design](mail-ingestion.md) and [acceptance](evidence/notification-transport-acceptance.json).


## Graph activity source addition

The tenant diagnostic category now routes Graph API-request logs to a dedicated East US workspace in kb-agentdemo. A workspace transformation keeps only enrolled pilot/collector application contexts and drops query strings and unused fields before storage. The certificate-based audit identity reads only the conditioned Graph table, then persists minimized encrypted source records with independent event/ingestion times. This is API evidence for later correlation, not proof of an AI actor or of generated wording. See [the Graph source review](graph-activity-logging.md).

The new logging workspace uses public Azure TLS ingestion/query endpoints with
Entra authorization. It does not inherit storage's operator-IP firewall; private
endpoints are outside this minimal-cost POC. Source delivery remains pending until
the live trace and durable-ingestion checks pass.

The recovery test adds a separate synthetic canary table/DCR and redacted DCR error
stream, each with seven-day retention. Canary publishing is operator-only at that
DCR. The [accepted archive diagnostic](graph-route-isolation-proposal.md) temporarily
routes tenant-wide raw Graph metadata to a separate restricted Standard LRS account
to isolate delivery faults; it bypasses the product's pre-storage transformation.
It has an explicitly accepted account-specific trusted-services exception and an
operator-only container read grant. The test stops that temporary export afterward.
Its raw metadata must not be described as synthetic-only or become product evidence
without the reviewed minimization, source qualification and authorization controls.

## Evidence ledger addition

An operator-enrolled observer supplies a current source/version-bound observation.
The ingestion bridge verifies committed identifiers, content digest, extraction and
scope against an already-authorized transient snapshot. It does not fetch a body or
change mail. Plain text is discarded after tenant-keyed matching material is formed;
complete payload matching stays unavailable when recipients/content are incomplete.

The separate authenticated evidence API accepts only scope-bound signed records from
an enrolled application identity. Its restricted SQL role appends encrypted receipts
and input revisions and rechecks current trust/expiry while reconstructing a view.
Agent execution, generation/inclusion, edits and copy mappings remain distinct.
Source private signing keys stay with their source; tests generate fictional keys.

Seven-day raw evidence and thirty-day input metadata have independent access expiry
and operator cleanup. Metadata bindings, signatures, append-only grants/triggers and
independently held anchors address different integrity risks. They do not claim WORM
storage or recovery of deleted model inputs. See [the schema](evidence-schema.md)
and [retention/correlation rules](correlation-rules.md).
