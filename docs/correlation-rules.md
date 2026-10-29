# Evidence correlation rules

Rule version: `correlation-v1`. These classifications describe evidence relationships;
they are not calibrated detector scores or a production accuracy qualification.

## Identifier and copy boundaries

A message reference is tenant/mailbox scoped and derived from a provider namespace
and case-sensitive immutable identifier. External-source IDs also include their
source namespace. An Internet Message-ID is not globally unique and cannot merge
sender/recipient copies. A signed mapping can connect two independently observed
copies; a mapping never propagates an actor or generated origin to the other copy.
Archive/store-ID translations require an explicit enrolled source mapping. Forward
relationships remain context, not equality. Exchange and Graph immutable/store IDs
are not treated as interchangeable.

Exact Internet Message-ID action matching requires one observed sender copy in the
same tenant/mailbox. Duplicates become candidates. Subject/time/body/recipient
similarity can never satisfy an exact identifier link. Identical subjects and bodies
on concurrent sends remain separate observations. Source event time, capture time and
receipt ingestion time are preserved separately. Latest-version status means latest
unambiguous **observed ledger version**, not a promise that the mailbox cannot have
changed since collection. Tied or superseded versions cannot yield an exact current
link; consumers must request the current source version before presenting a decision.

## Independent evidence paths

| Input | Required for `exact` evidence linkage | Otherwise |
| --- | --- | --- |
| Send execution | Enrolled source/capability, signature, current trust and scope, observed sender/sent copy, exact supported identifier, completed outcome, established actor without a contradictory known mechanism, matching send time within two seconds | Candidate, invalid or conflicting; never a positive from an accepted API request/read/draft |
| Generation | Authenticated source record and output digest | Context only, even if the wording matches |
| Content inclusion | Current generation parent in the same mailbox, new generated origin, in-scope assistance category, authenticated transfer lineage, matching digest on an observed authored span, causal event order | Candidate/invalid; similarity, echo, shared boilerplate and basic corrections do not establish generated origin |
| Content edit | Current trusted generation/inclusion parents, same-copy before/after references, authenticated unchanged generated span and matching observed ranges/digests | Changed or unverifiable output breaks the exact lineage; a substantive new AI rewrite needs its own generation/inclusion records |
| Copy mapping | Enrolled authenticated source mapping, observed scoped endpoints, same tenant, complete matching payload, appropriate relation | Candidate; no inherited actor/content claim |

An output may be legitimately reused in another message, but each message/version
needs a new inclusion event. A parent from another mailbox is not searched or accepted.
Inherited regions remain context even when they contain matching AI output. Short
common greetings cannot become verified origin merely through a hash/string match;
the causal generation/transfer evidence is essential. A dishonest trusted source
can still make a false claim; a signature is not a proof of truth.

Action and content links use different facts and predicates. Generation, inclusion,
edits or content invalidation cannot introduce an agent-send link. Ordinary sending
mechanisms and unobserved source activity stay unknown unless a qualified action
source establishes them. Statistical content inference remains uninstalled; its
later output must not change action attribution.

## Replay, conflict, trust and reassessment

Event identity is `(scope, issuer, event_id)`. An identical record replay returns the
existing reference without another event. A different validly signed record reusing
that identity is rejected and its conflict digest is committed separately, without
overwriting the original. Conflicting completed executions downgrade exact action
links; invalid evidence affects its own axis. Invalid content parents do not downgrade
an otherwise supported independent action chain.

Key rotation appends a new pinned key with explicit issue-time validity. Old valid
records can be verified during their evidence lifetime until revoked. Revocation is
immediate and fail-closed, for a specific key or the entire issuer. Re-signing an old
event with a replacement key cannot replace/resurrect its original revoked record.
Issuer identity/capabilities and public keys cannot be silently overwritten.

Every current view rechecks signatures, scope, lifetime, conflicts and current
revocation state, including content parents. Historical input revisions retain what
was observed then, explicitly labeled historical. Reassessment uses the versioned
`.../inputs` operation to append a new server-computed view with the prior reference;
old results are not edited. Consumers must not use a historical snapshot as a current
trust verdict. The later decision worker is responsible for scheduling reassessment
of cached product findings; this milestone supplies the current-trust gate and
append-only reassessment operation.
Revision numbers are ordered within an authenticated history epoch. Once its last
retained input expires, the next assessment starts a new epoch; old expired rows can
remain until physical purge without blocking that assessment or extending retention.

## Ingestion integration

The bridge takes an already-authorized transient snapshot; it performs no Graph
read or body lookup. Operator enrollment verifies the committed mailbox source's
tenant/mailbox binding. Observation requires a committed, current, in-scope ingestion
version, exact identifiers and content digest, and the same extraction contract.
Changed bodies/IDs, stale versions, expired raw linkage and unsupported offset
conversions are rejected. The source/version reference is retained in the ledger.

The existing ingestion reader does not establish sender execution and omits complete
recipients. The bridge preserves those limits: unknown copy role remains unknown and
complete-payload matching is unavailable. Synthetic tests use a simulated source;
`committed_ingestion` identifies the internal durable path, not live Microsoft
authentication or detector accuracy. Source-specific live adapters remain later work.

## Retention and replay matrix

| Material | Maximum accessible period | What remains possible |
| --- | --- | --- |
| Signed envelopes / encrypted observation material | Seven days; signed evidence may expire sooner | Revalidate active signatures and reconstruct current evidence links |
| Explicitly authorized raw snapshots | Existing seven-day snapshot policy | Read/re-run only with actual retained bytes, authorization, compatible normalization and pinned model artifacts |
| Sealed input metadata and digests | Thirty days | Inspect historical source/schema/rule references; not reconstruct deleted text or re-execute an uninstalled model |
| Independent history anchor | Until earliest included input expires | Detect prefix removal/modification while allowing valid later appends |
| Trust/configuration records | While enrolled / needed for trust management | Preserve key, capability and revocation history without retaining email text |

Expiry is checked before decryption/use and independently enforced by runtime SQL
policies. Operator-only `purge_expired` physically removes expired inputs, conflicts,
receipts and unreferenced observations. Runtime identities cannot invoke privileged
deletion. Retention maintenance must be operated regularly; access expiry is not a
claim of instantaneous physical erasure. A snapshot reference by itself is not proof
that bytes still exist. The API reports that distinction and always reports model
re-execution unavailable in this model-absent milestone.

Graph activity-log delivery remains unqualified. Its absence supplies no negative
agent evidence and does not alter an independently qualified Exchange audit source.
