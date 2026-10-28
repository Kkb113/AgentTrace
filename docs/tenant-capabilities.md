# Tenant capability matrix

This is the historical feasibility probe. Current scoped application access and effective tests are recorded in [the secure-access report](secure-access-report.md); the temporary feasibility reader remains retired.

Read-only probe run: 28 October 2026, 13:28 UTC. Raw output is ignored at `work/private/tenant-preflight/tenant-capabilities.private.json`; no tenant, subscription, mailbox, app or resource IDs are committed here.

| Capability | Evidence | State and implication |
| --- | --- | --- |
| Required group and explicit subscription | `group show`, `resource list`, selected account context | Observed; `kb-agentdemo` exists, metadata region East US, shared resources present |
| Exchange/Entra plans | Tenant subscriptions and operator-assigned plan reads | Relevant successful service plans observed; not a proof of every audit entitlement |
| Operator administrator role | Directory-role membership read | Elevated administrator role observed; application access remains separately scoped |
| Agent-identity metadata API | Beta agent-identity collection read | Readable; registration is not per-email execution evidence |
| Test-mailbox API read | Exact synthetic subject-prefix filter, five metadata-only records maximum | Denied with current CLI session; not interpreted as absence of messages |
| Authorized temporary reader | Owner-approved single-tenant public client; two delegated resource scopes; operator-only consent | Registration and consent verified; zero secrets/certificates and no application-only permission. Separate from future product identity |
| Reader browser sign-in and mailbox read | MSAL PKCE with validated operator/tenant claims; exact Internet Message-ID and subject filters | Succeeded; two synthetic copies retrieved, including non-draft Sent Items copy. Device-code flow was blocked with 53003; policy was not changed |
| Reader Exchange audit search | Narrow actor/message/window/Send filters | Succeeded; one successful Send event for the Claude message, with exact item Internet Message-ID, tenant/mailbox and connector application context. Completed control searches produced no matching Send record at collection time |
| Outlook interactive observation | Existing signed-in Outlook web session | Marked self-addressed test observed and exported as EML; this is an operator capture, not a programmatic product collector |
| Claude source trace | User supplied exact tool name, parameters and literal send result, followed by a separate sent-message lookup | Real source information available; no ID/request/timestamp in send response, so causal message binding remains insufficient |
| Graph activity-log destination | Existing Entra diagnostic settings read | No enabled Graph activity-log destination observed. P1 eligibility alone does not enable it |
| Existing workspace's synthetic-test window | Narrow Graph send-request metadata query in the existing in-group workspace | Query succeeded with zero matching send-request rows in the five-minute test window; this is not proof that an agent did not send or that no later evidence can arrive |
| Office 365 audit-feed API | Existing subscriptions/list GET | Unauthorized because CLI token has `user_impersonation`, not required activity-feed permission. No subscription started or changed |
| Exchange audit enablement / Send population | Actual authorized Exchange audit search | Send population observed for the Claude self-test. Full organization auditing configuration and every event entitlement are not inferred from this one event |
| Actual audit availability | Linked event + collector first successful read | Claude Send event available by 3,429.482 seconds after event time; exact ingestion latency unmeasured because access was established later. Controls had no returned Send record at collection time; missing records are not human evidence |
| Copilot generation history | Licensing/route/scope feasibility | Optional, unconfigured. Claude manual-copy experiments do not depend on it |
| Outlook add-in auth | Supported NAA/MSAL design from Microsoft guidance | Candidate design only; no runtime add-in test claimed |

The baseline preflight uses existing human administrator credentials only to read selected configuration. The later temporary reader is separately authorized and documented in `access-remediation.md`; it is not the registered product identity. Its MSAL tokens stay in process memory. The product feasibility CLI has no provisioning, consent, mailbox-write, send, schedule or approval command. It invokes Azure CLI's Python entry point on Windows to preserve Graph query strings containing `&` without passing them through a batch shell.

Optional unavailable feeds have explicit unknown/coverage behavior. The authenticated Exchange event closes the minimum Claude send-to-message feasibility dependency through a unique tenant/mailbox-scoped Internet Message-ID join. Store-to-Graph immutable-ID equivalence remains unestablished and is not used as proof. The owner-authorized temporary registration/consent is recorded explicitly; no Conditional Access policy, logging destination, new license, Azure role or product deployment was silently changed.
