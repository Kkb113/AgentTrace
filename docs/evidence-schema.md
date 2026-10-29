# Evidence ledger contract

Version: evidence schema `1.0`, correlation rules `correlation-v1`. The ledger stores
and correlates detection evidence. It has no email-sending, drafting, generation or
approval-management operation. Its correlation API does not emit final product flags;
the later decision engine consumes these qualified inputs for the two independent
findings, `agent_send_attribution` and `content_assessment`.

## Records and trust boundaries

| Record | Identity and validation | Storage |
| --- | --- | --- |
| Scope | Explicit tenant/mailbox pair and database-role ACL, enrolled by migration operator | Standing configuration |
| Observer | Operator-enrolled source, namespace, schema and capture basis | Standing configuration; runtime cannot enroll |
| Message observation | Scope, source/event/version references, case-sensitive provider identifier, observed state/copy role, source and capture times | Sensitive identifiers become tenant-keyed fingerprints; canonical material and its metadata binding are encrypted |
| Issuer/key | Exact application client and subject, allowed fact kinds, pinned Ed25519 public key, issue-time validity | Operator-only append; rotation adds a new key; revocation adds a permanent record |
| Signed evidence | Issuer, event UUID, exact scope/message/version, occurrence/issue/expiry times, schema and discriminated fact | Signature checked against enrolled identity/capability; envelope encrypted; seven-day maximum |
| Input revision | Reconstructed correlation view, source/schema/digest references, rule version, history epoch, prior input and revision number | Encrypted and authenticated metadata, append-only, thirty-day maximum |
| History anchor | Ordered input references/digests and expiry, authenticated with the tenant key | Held independently by an operator; expires with its earliest retained input |

Frozen JSON Schemas are in `packages/contracts/schemas/`: `signed-evidence`,
`message-observation` and `correlation-view`. Unknown fields, wrong types, unsupported
algorithms/canonicalization versions, duplicate JSON keys and nonfinite JSON numbers
are rejected. Evidence requests are limited to 65,536 bytes before schema parsing.
Every stored input identifies its observation source/event, source schema,
canonicalization/normalization versions, evidence/issuer/key references and digests.
Unsupported or invalid evidence is visible as such; unavailable provenance is not
silently turned into a human-origin result.

The closed facts are `send_execution`, `generation`, `content_inclusion`,
`content_edit` and `copy_mapping`. Generation facts describe the assistance category
and established provider/model reference when available. They contain an output
digest, not prompts or generated text. Inclusion/edit facts describe explicit parent
evidence and observed spans. Before/after references are digests, not retained text.
Send facts distinguish attempted, accepted, failed and completed execution. A signature
authenticates a source's claim; it cannot establish that a compromised or dishonestly
enrolled source is telling the truth. Source-specific semantic qualification remains
required when adapters are introduced.

## Canonicalization

`evidence-json-v1` is a project-specific, closed-model encoding, not an RFC 8785/JCS
implementation. It uses UTF-8 JSON, sorted string keys, compact separators, UUID
strings, fixed microsecond UTC timestamps, and no floating-point values. Identifiers
are byte-sensitive. The signed bytes include a protocol domain, the algorithm, key
reference and entire record. No token-provided URL or key is fetched.

`mail-text-v1` normalizes decoded text to Unicode NFC and LF line endings. It preserves
case, spaces and punctuation. Recipient domains are lowercased; local parts retain
case. Recipient roles remain distinct; duplicates are removed within the same role
and ordering is canonical. A canonical payload includes subject, decoded body and
known-complete recipients. Unavailable body/recipient information produces an absent
complete-payload digest, rather than a fingerprint of falsely complete empty data.
Content spans use code-point offsets in this canonical text. Overlapping/out-of-range
spans are rejected. Authored and inherited regions remain distinguishable.

Transport MIME digests remain separate. Equal canonical text does not prove equal
MIME, equal attachments, equal execution or authorship. Quoted text, HTML extraction,
Unicode composition and transport rewriting require explicit version/offset mappings;
the ingestion bridge rejects unsupported offset conversions. It preserves
`text-extraction/1.0` separately from the canonical matching version.

Identifiers, content/recipient fingerprints and snapshot references are sensitive.
Fingerprints use HMAC-SHA256 with tenant-specific private keys and domain separation;
there is no global content search or cross-user generation-history search. Keys are
loaded from protected files, outside Git and the database. Application logs contain
fixed event/outcome codes and pseudonymous subject references only.

## API and authorization

The separate gateway binds to `127.0.0.1:8082` and publishes OpenAPI at `/openapi.json`.
The original foundation decision API remains separate. The new API accepts evidence
and stores detection input revisions; none of its POST routes execute email actions.

| Route | Authorization / behavior |
| --- | --- |
| `GET /health/live`, `/health/ready` | Liveness; readiness verifies ledger schema and configured token validation |
| `POST /v1/evidence/receipts` | Entra API token, server-owned message/mailbox entitlement, application identity matching issuer enrollment, capability and valid source signature |
| `GET /v1/evidence/messages/{message_ref}/versions/{version_ref}` | Entra token and explicit message entitlement; reconstructs evidence with current trust |
| `POST .../versions/{version_ref}/inputs` | Entitled delegated investigator/administrator; records a new input revision from server-computed evidence |
| `GET /v1/evidence/messages/{message_ref}/history` | Entitled reader; historical snapshots explicitly require current-trust reassessment |

The established validator still restricts application tokens to `Detection.Viewer`.
That role alone cannot publish evidence: separate operator enrollment, exact
application/subject binding and a valid issuer signature grant the narrow submission
capability. Delegated tokens cannot publish as an application issuer. No Microsoft
365 permission or tenant app-role change is made in this milestone.

Malformed payload errors omit the input. Unknown/unauthorized references use 404;
unaccepted authenticated source claims use a generic 403; altered event reuse uses
409; storage/integrity failures use safe unavailable responses and never acknowledge
successful persistence. Views are capped at 1,000 receipts and histories at 100
retained revisions; overflow is explicit and not silently truncated.

## Storage integrity and remaining privileged risks

`ledger.sql` is an additive migration with a separate schema-version marker. Runtime
roles have no UPDATE, DELETE, TRUNCATE, trust-enrollment or schema-owner permission.
Row-level policies require an enrolled tenant/mailbox scope and current retention.
The collector alone writes observations; the ledger identity appends receipts,
conflicts and input revisions. The content identity receives no ledger access.
Existing API/attribution identities can read permitted metadata columns, not raw
receipt, observation or input ciphertext.

Triggers also prevent accidental privileged rewrites/truncation. Envelopes use AEAD
encryption with record contexts; observed message/header fields and history metadata
are bound inside authenticated material. Sealed input digests and an independently
held history anchor detect modification and rollback in their stated scope. Concurrent
submissions, revocations and revision creation serialize under a scope transaction
lock; revision order does not rely on a transaction's pre-lock start timestamp.
When all retained history expires, a new authenticated epoch starts at revision one.
Expired rows awaiting physical cleanup cannot collide with that new epoch. Live
epochs must extend their prior revision; they cannot silently fork or reset through
the application. A nonempty pre-epoch development preview fails migration for explicit
review rather than silently relabeling authenticated history.

This is application-level append-only storage with tamper detection, not a claim of
WORM storage or protection from a database owner changing DDL plus compromising the
external keys/anchor. No database hash alone is advertised as an immutable ledger.
Source compromise, missing external anchors and deletion after expiry remain explicit
limits. A deployment requiring regulatory WORM/FIPS certification needs a separately
accepted storage/cryptographic policy and operational qualification.

References: [Ed25519 API](https://cryptography.io/en/latest/hazmat/primitives/asymmetric/ed25519/),
[PostgreSQL row security and its limits](https://www.postgresql.org/docs/17/ddl-rowsecurity.html),
[PostgreSQL trigger behavior](https://www.postgresql.org/docs/17/sql-createtrigger.html).
