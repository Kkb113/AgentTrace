# Agent sending applications

AgentTrace can enroll more than one sending application without inventing a universal AI header. The production rule uses the actual Exchange Send executor, not an application display name, email prose, test subject, existing category or user-reported action. The old `watch-incoming-mail.py` demo remains experimental: its Gmail API trace match does not identify ChatGPT or distinguish ordinary API applications.

## Routes and qualification

| Route | Required observations | Current interpretation |
| --- | --- | --- |
| Existing Claude Microsoft 365 route | Exact MCP declaration, successful enrolled Send, current publisher pins and unique scoped copies | Existing qualified POC rule |
| ChatGPT through the enrolled mailbox's Outlook connection | Successful Send with matching outer/nested application IDs, exact enrolled application/publisher/owner pins, tenant/mailbox/message/time checks and unique scoped copies | Live synthetic test passed; AI Agent was applied and read back in Outlook |
| Another dedicated agent application sending through Exchange | The same authenticated execution/publisher/copy checks | Supported enrollment mechanism; live qualification is required for each additional application |
| ChatGPT Gmail to Outlook | Gmail HTTPREST trace; user-provided send result | API hint and test ground truth respectively; neither supplies authenticated provider identity to the receiving detector. Unknown under the production API-only rule |
| Another agent, workflow platform or shared API application | Name, brand header or API traffic alone | No automatic enrollment. Qualify its execution source and exclusivity first |
| Normal browser/email client with no automation indicators | Complete supported-field inspection | Human under the accepted compatibility policy; this does not prove who controlled the browser |

The synthetic ChatGPT Outlook message received on 30 October 2026 has no `x-ai-generated` declaration. Live qualification found its successful Exchange Send event: both application-ID fields matched the enabled ChatGPT application, whose verified publisher is OpenAI, L.L.C. Current exact pins, scope/time/Message-ID and a unique provider-copy pair passed. The normal collector persisted AI Agent and the scoped writer applied/read back the category while preserving headers/read state; repeat application was a no-op. See [the validation record](evidence/agent-provider-validation.json). This qualifies the tested own-mailbox connector route, not every ChatGPT deployment or external sender.

The owner's pasted send transcript is ground truth for the test, not a production feature. The Outlook tool's null result is not delivery proof. The separately read provider messages establish arrival. A Gmail-local message ID is not interchangeable with an Outlook immutable ID or Internet Message-ID.

## Explicit enrollment

`sender_source.agent_providers` is an optional list in the private runtime configuration. Empty/omitted lists preserve the existing Claude enrollment hash. Each additional profile pins a client UUID, publisher identifier and publisher owner tenant, plus an explicitly qualified send-evidence mode. No name lookup automatically modifies configuration. Example values below are fictional:

```json
{
  "provider_key": "qualified_agent_connector",
  "client_id": "00000000-0000-4000-8000-000000000050",
  "publisher_id": "verified_publisher_identifier",
  "publisher_owner_tenant": "00000000-0000-4000-8000-000000000051",
  "send_evidence": "exchange_send",
  "declaration": "authenticated_application"
}
```

`authenticated_application` is suitable only when the independently qualified application identity represents the agent's email sending capability. A shared automation application that can also perform non-AI sends cannot qualify through this identity alone. `mcp_office365` additionally requires the exact single known declaration. Unknown/conflicting declarations reject either route. Duplicate application IDs, duplicate provider keys and overriding the built-in Claude profile are rejected.

Qualification sequence:

1. Independently send a synthetic message through the candidate, recording the actual tool operation/result as test ground truth. Include a normal-client control and ordinary non-AI API counterexamples.
2. Read only the exact designated synthetic messages. Record source authentication/custody privately. Verify the candidate's exact registry identity/publisher and its dedicated agent-send semantics.
3. Search the already authorized mailbox's Exchange Send records with the exact bounded event window. Complete pagination. Validate event success, tenant/token tenant, mailbox owner/GUID, outer/nested client IDs, request context, event identity and timestamps. No successful event means no qualified agent send.
4. Resolve a unique Sent/received copy pair with matching message context. Observable copy collisions, stale/revoked publisher pins, failed actions and scope conflicts reject the positive.
5. Run the persisted decision, current-evidence/category admission and replay regressions. Retain a sanitized validation report; do not claim population accuracy from a few live cases.
6. Enroll the reviewed profile in a **new private dry-run state** with the same mailbox scope. Adding/changing a profile in a bound state fails with `sender_enrollment_changed_requires_review`. Do not delete/rewrite the old enrollment metadata to force acceptance. Retain existing state/history and assess any outstanding annotations before a deployment transition.

The new rule is `sender-rules/provider-corroborated/v1`; its decisions include a `provider-sha256` reference binding the exact profile as well as audit, publisher, copy-context and snapshot evidence. Decision persistence, preview and writer recomputation all require that same trusted configuration. A source packet's self-asserted provider identity cannot enroll itself. Existing Claude assessments keep their original rule version.

## Run and inspect

With the private, reviewed runtime configuration and existing read-only identities:

```powershell
uv run python scripts/monitor-outlook-mail.py --config <private-runtime.json> --check
uv run python scripts/monitor-outlook-mail.py --config <private-runtime.json> --dry-run
# Stop with Ctrl+C before inspecting the same locked state.
uv run python scripts/monitor-outlook-mail.py --config <private-runtime.json> --inspect-rules
```

The collector refreshes evidence asynchronously. With additional enrolled providers, pending authenticated-source searches stay Unknown. A completed empty search is not proof of an agent or a biological human; the existing supported-field compatibility policy still applies. Category application remains a separately guarded explicit operation; these commands send no email and change no categories. The frozen experimental terminal command is unchanged and must not be used as qualification evidence.

The local qualified dry-run configuration is `work/private/agent-provider-monitor/runtime.private.json`. It includes the private ChatGPT pins and points to a separate state; the previous monitor configuration/history is retained. It is ready for supervised deployment review in Phase 7. No background worker or unattended category writes were enabled by this qualification.

No additional Azure resource, premium license purchase or new OAuth permission is required for this extension to the existing authorized Exchange audit/registry readers. It does require those readers to remain available. Operator publisher access and delayed Microsoft audit ingestion remain operational dependencies; Phase 7 must validate them under the designated runtime account.

## Limits and sources

Microsoft documents client application fields and Send semantics in its [Exchange audit record reference](https://learn.microsoft.com/en-us/purview/audit-log-exchange-properties). Audit evidence is asynchronous: [Microsoft's audit search guidance](https://learn.microsoft.com/en-us/purview/audit-search) describes typical Exchange availability of 60–90 minutes, with no immediate-delivery guarantee. Headerless attribution therefore cannot promise an instant red category.

Where an eligible OpenAI deployment exposes authenticated tool-call records, those may support a future source adapter. [OpenAI's dots administration documentation](https://learn.chatgpt.com/docs/enterprise/dots-admin-guide) describes compliance coverage for supported deployments; it does not establish this account's access or that every connected-app action is exported. Neither a pasted assistant response nor a generic Gmail API trace substitutes for such an adapter.

The approved POC correlation still permits an unobservable replacement preserving every checked field. It is corroborated evidence, not independent forensic received-item identity. Browser-controlled agents retain the owner's Human compatibility label. External sender tenants and personal Gmail execution remain outside the receiver's automatic audit visibility.
