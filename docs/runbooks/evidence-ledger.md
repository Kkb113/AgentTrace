# Evidence ledger operations

This milestone is a local synthetic sandbox. No new Azure resource, Microsoft 365
permission, customer-history connector or email execution capability is provisioned.
The existing Graph diagnostic investigation remains separate and unqualified.

## Bootstrap and service identity

1. Run `python scripts/dev-services.py start`. The additive migration creates ledger
   tables and the separate `agenttrace_ledger` SQL login with its generated local-only
   credential. Existing mailbox/audit ingestion is preserved.
2. Store a private JSON key configuration outside Git, normally under the protected
   `work/private/evidence-ledger/` directory. Its exact structure is:
   `schema_version: "1.0"`, `encryption_key: base64(32 random bytes)`,
   `tenant_fingerprint_keys: {tenant UUID: base64(distinct 32 random bytes)}`.
   Use cryptographic random bytes. These are ledger encryption/fingerprint keys,
   not a source's private signing key. Never replace an existing file to "reset"
   setup. Replacing encryption/fingerprint keys requires a versioned migration and
   retained-key/re-encryption plan; silent in-place rotation is unsupported.
3. As the migration owner, construct `EvidenceLedger` with `load_ledger` and reviewed
   private settings. Use `enroll_scope`, `enroll_observer`, `enroll_issuer` and
   `enroll_key` to establish explicit scope, source/schema, client/subject, allowed
   fact kinds and public verification keys. These are operator library operations,
   not public API routes. Grant only required database roles to a scope. The receiver
   cannot enroll or change trust. A duplicate conflicting key/issuer enrollment
   fails rather than overwriting trusted state.
4. For an existing mailbox source, `enroll_ingestion_source` checks its encrypted
   tenant/mailbox binding. `observe_ingested_snapshot` accepts only a committed
   current version and an already-authorized transient snapshot. It makes no Graph
   call and cannot bypass the ingestion folder/body policy. Ambiguous extraction
   remains unavailable for authored-content lineage.
5. Provide a server-owned `AuthorizationPolicy` file with the exact tenant/audience,
   clients, subject-to-mailbox entitlements and message-reference-to-mailbox mapping.
   Ledger mailboxes are UUID identifiers. Do not let receipt parameters populate
   entitlements. Real Entra validation uses its configured tenant JWKS; fictional
   local JWKS are restricted to the existing synthetic environment.

Run the gateway as the dedicated runtime identity, for example from PowerShell:

```powershell
$env:AGENTTRACE_ENVIRONMENT = 'local_synthetic'
$env:AGENTTRACE_DATABASE_USER = 'agenttrace_ledger'
$env:AGENTTRACE_DATABASE_PASSWORD_FILE = 'C:\AgentDetection\work\local\roles\ledger-password'
.venv\Scripts\python.exe -m agenttrace_ledger.runtime `
  --keys work/private/evidence-ledger/runtime-keys.private.json `
  --authorization work/private/evidence-ledger/authorization.private.json
```

The process refuses the migration-owner login. It binds only to loopback port 8082;
`/health/ready` checks the ledger schema and configured authentication. Uvicorn access
logging is disabled. Production ingress/TLS/hosted identities remain later deployment
work; do not expose this local endpoint publicly or claim a hosted release.

## Submission and reassessment

An external source retains its private signing key and signs the domain-separated
canonical `SignedEvidence` bytes. The receiver knows only the enrolled public key.
Application access tokens retain the existing viewer-only restriction; the explicit
issuer enrollment plus signature supplies the separate narrow publishing capability.
Ordinary viewers, delegated users, unsigned declarations and unknown issuers cannot
publish as that source. Do not register a sender application as an agent merely
because it can send email. Qualify source truth/semantics independently.

Read the current versioned evidence view before making a decision. To retain its
input basis, an entitled delegated investigator invokes `.../versions/{version}/inputs`.
That operation computes the view server-side, serializes revisions and appends the
prior reference. No client-supplied verdict is stored by this API. After revocation
or conflict, current views fail closed immediately; record a new input revision to
preserve the reassessment. Historical snapshots remain historical and cannot serve
as current trust assertions.

Key rotation uses a new public key reference and validity interval. A key or issuer
revocation is append-only and permanent for that enrollment. Coordinate revocation
across all explicitly enrolled scopes of a compromised source. New keys do not
resurrect records accepted under a revoked key. New trust requires a separately
reviewed enrollment, not deletion of revocation history.

## Integrity, retention and recovery

- Use `checkpoint` to export an authenticated history anchor to independently held,
  protected operator storage. `verify_checkpoint` rejects missing/reordered/changed
  prefixes and permits valid later appends while the anchor is within retention.
  Exporting and retaining an anchor is an explicit operational responsibility; a
  database-only copy cannot protect against rollback of the whole database.
- Run operator-only `purge_expired` regularly. It removes expired thirty-day input
  metadata and seven-day raw envelopes/observation material in dependency order.
  Runtime RLS and application gates deny expired data before physical cleanup.
  Do not disable append-only triggers or use TRUNCATE as routine cleanup.
- Snapshot references do not prove byte availability. Read snapshots only through
  the existing authorization/expiry gates. Deleted text cannot be reconstructed from
  a keyed digest. A retained input also needs pinned model/normalization artifacts
  for model replay; this milestone has no installed statistical model.
- Missing tenant keys, bad tags/signatures, stale versions, revoked parents, ambiguous
  links and unavailable storage must produce named invalid/unavailable states, never
  a new positive. Restore only approved matching keys/configuration and retry reads;
  do not relax tenant checks or convert unknowns to human-origin findings.
- Evidence-view/history bounds fail explicitly. A future bounded-export interface
  needs its own continuation contract; operators must not silently truncate the input
  used for a decision or raise limits without reviewing memory and privacy effects.

Run `python scripts/verify-foundation.py`, then
`python scripts/verify-evidence-ledger.py` to check all recorded exits. The first
includes real PostgreSQL logins, a real loopback HTTP restart test, schema contracts,
signature/lineage negatives, tampering, rollback and retention cleanup. Test tokens
and receipts are independently signed fictional fixtures; these tests do not prove
live provider coverage or false-positive rates.
