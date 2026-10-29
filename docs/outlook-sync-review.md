# Mailbox synchronization engineering review

Phase 2 implements reliable, read-only incoming-mail synchronization in the separate Outlook runtime. Per-folder delta and recursive discovery checkpoints, pending detail work, membership reconciliation and recovery states are durable. The archived binary demo, unrelated evaluation work and client workbook are preserved. No new Azure resource, OAuth grant, category write or send operation was introduced.

## Exit assessment

| Exit | Evidence | Result |
| --- | --- | --- |
| Every controlled observable message is accounted for or has an explicit gap | 10,023-message inventory, receiving/excluded/new/nested/hidden/removed folders, current-ID reconciliation, missing-item and expired-cursor gap tests; actual Gmail-to-Outlook arrival and three moves | Pass |
| No population/page/session cap silently discards mail | Unfiltered initial delta, durable next/delta links and work, bounded fair scheduling, backlog age/ready/pending/dead-letter counters; a mid-backlog restart drains all 10,023 IDs | Pass |
| Restart/move/replay creates one decision per relevant version | Six subprocess crash cases around discovery/delta/detail commits; stale-response rejection; repeated IDs, duplicate Internet IDs and received-copy moves; live four-stage chain retains one immutable ID, observation and decision | Pass |
| Category-generated delta cannot cause decision/write loops | Semantic digest excludes categories/read state/location/change key; echo tests preserve one decision/preview, real header changes version it; no category writer exists yet | Pass |

[Executed evidence](evidence/outlook-sync-validation.json) records the tested source digest, counts and live-versus-simulated limits. [Runbook](runbooks/outlook-mailbox-sync.md) explains operation, private configuration, recovery and scope. The published PR additionally runs all shared gates on its exact commit.

## Review and fixes

Review followed source request → page validation → transactional work/checkpoint → current-message resolution → observation/preview, then migration, fault and restart paths. Source request URLs remain fixed-mailbox GETs. Continuations require the exact Microsoft origin, mailbox, collection and field selection; malformed or foreign links fail without committing page effects. The reviewed certificate helper now bounds MSAL HTTP requests at twenty seconds; signing and Graph requests already have timeouts. Credential/source exceptions never become actor evidence or leak raw third-party text through the process boundary.

The additive v2 migration verifies v1's exact structure/digest before modifying it. Its transaction preserves activation and existing pending work. Each discovery page stores folders, child jobs and continuation together; each delta page stores membership hints, detail jobs and continuation together; each detail transaction stores snapshot, observation/work and acknowledgement together. Injected failures and abrupt subprocess exits prove rollback/replay at all three boundaries. A generation comparison rejects delayed responses after progress. SQLite remains a local, single-host, single-connection design protected by the Phase 1 OS lock and lease.

Tests exposed an initial-cycle issue where discovery waited until another runner cycle; discovery now starts as soon as the system-folder exclusion inventory completes. Review also replaced wall-clock scheduling with a persisted monotonic turn counter, preventing large populations or equal timestamps from starving discovery/other folders. A receiving folder that becomes excluded now queues current-copy reconciliation rather than retaining an eligible preview indefinitely.

Message membership hints are never used alone to claim global deletion. Every changed/tombstoned item is resolved using its mailbox-scoped immutable ID. Current metadata wins over stale delta ordering. The decision fingerprint ignores service categories and other display-only changes. A separate revision counter records real evidence changes, including evidence changing back to an earlier value, without merging copies that share an Internet Message-ID.

Source retry states preserve their cursor and due time. Authorization failures/malformed input block a job; transient retry exhaustion becomes a dead letter. Retry-After is a lower bound with positive jitter. The reused transport's hour cap is handled by blocking for operator review rather than retrying an unknown longer interval early. Explicit retry does not clear a gap; successful checkpoints may close recoverable outages while retaining history. An expired cursor's potentially unobserved interval remains an explicit unrecoverable gap after reconciliation.

## Actual live test

The owner manually sent a synthetic Gmail message to the enrolled Outlook mailbox, then moved that same received copy through Inbox → AgentTrace Synthetic → Junk → Inbox. Separate process launches resumed existing delta state at each stage. Four private proof packets compare the provider's selected synthetic message to the durable record; the immutable ID, observation revision and decision count remain unchanged. Final state has no pending message jobs, blocked jobs, dead letters or unresolved gaps. Provider identifiers/headers and configuration remain private with seven-day capture deadlines; only sanitized counts and proof digests are published.

The custom-folder test uses a manual move and validates the same receiving-folder collection path that rule routing uses; no mailbox rule was created. Rules arriving in a custom folder, nested/new folders, category echoes, deletion, missed polling, throttling and token expiry are independently exercised with deterministic source responses. Live tests do not establish synthetic accuracy ground truth, category display, Graph activity-log availability or a recovered interval that was not observable.

## Remaining gates

The current synthetic-only collection boundary selects eligible messages by the approved test prefix after minimum metadata inspection. Ordinary/historical subjects are discarded, their headers are not requested, and bodies/attachments are never requested. The prefix is an access/test-population selector, not a classifier signal or DLP guarantee. No production AI/Human rule is enabled; previews remain Unknown pending Phase 3 qualification.

Full production data enrollment, safe Outlook category writes, physical retention enforcement, encrypted backup/restore, host ACL provisioning, unattended supervision, throughput/latency qualification and independent accuracy evaluation remain later gates. Folder discovery is periodic and eventually consistent; transient hierarchy changes or inaccessible items remain visible gaps rather than proof of complete historical event capture. This phase qualifies current-state synchronization and its recovery contract, not an exactly-once forensic record of every provider intermediate event.

The complete shared engineering gates are run against an isolated selected-source export. The local regression stack uses a separate synthetic database volume and is stopped after testing; original volumes are retained. The one Windows symlink-creation test is platform-skipped locally and runs on Linux CI. No unresolved critical/high defect was found within this synchronization scope after the recorded fixes.
