# Three classification labels

The owner requested **AI Agent**, **Human** and **Unknown** as the only current detection labels on 30 October 2026, before Phase 7. This changes the display vocabulary and current output contract. It preserves the previously accepted evidence requirements and compatibility meaning of the green label.

| Label | Color | Meaning |
| --- | --- | --- |
| AI Agent | Red / preset0 | The supported rule corroborates agent submission with authenticated source evidence |
| Human | Green / preset4 | Complete normal-client-compatible inspection without observed automation indicators or conflicts, under the owner-approved policy |
| Unknown | Yellow / preset3 | Evidence is incomplete, conflicting, unavailable or unsupported |

Human is a policy classification, not proof of a biological controller. Browser-controlled agents can share this label under the existing policy. Text drafting origin does not establish the sender. Generic API use or an unsigned marker alone still cannot establish AI Agent. The AI rule, accuracy thresholds and supported source coverage are unchanged.

The active human rule is `sender-rules/human/v2`; the policy is `corroborated-poc-human/v2`. The policy-version change schedules fresh assessments. Current contracts, output and reports use the three names. Historical raw decisions and evidence remain unchanged. Read-only parsing recognizes the old Human-capable label only with its retired `sender-rules/human-capable/v1` version, preserves that version and displays Human. The retired rule is ineligible for a new category write; current evidence must be reassessed. Existing private display mappings normalize the old name to Human. The legacy SQLite enum remains for existing historical rows, not as a fourth active verdict.

The owner-requested rename was completed through Outlook web without recreating the retired setup app or adding permissions. The [Graph update API](https://learn.microsoft.com/en-us/graph/api/outlookcategory-update?view=graph-rest-1.0) changes category color but does not rename displayName. Outlook replaced the old master-category ID. Before the change, the operator recorded the old owned registry and full category inventory and backed up runtime state. Afterward, an authenticated read verified one green Human definition, absence of the old definition/name and identical unrelated definitions. The new owned mapping records explicit owner-action provenance and its private receipt digest. Its definition digest is a normalized provider readback, not an application POST response or Microsoft-signed attestation. No unowned same-name category was adopted.

The Red category tags previously added as preservation controls were removed only from the two exact synthetic test messages. That pre-existing personal master definition and all other unrelated categories were preserved. AgentTrace neither creates a fourth classification nor deletes the user's own category system. Cleanup preserved message headers and read state and used current-version conditional updates. The earlier Phase 6 report remains accurate about the controls left at that time; the [new executed record](../evidence/simple-labels-validation.json) records their subsequent removal.

The desktop category list appeared stale while Outlook web and Graph showed the owned definitions. Desktop UI control was stopped by the user; subsequent validation uses the existing APIs, not more desktop input. A cached Outlook client may need refreshing or reopening. Server inventory and message readback are verified separately from the later full supported-client display gate. Automatic monitor application remains disabled.
