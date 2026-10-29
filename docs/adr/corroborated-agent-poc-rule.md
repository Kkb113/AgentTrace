# Accepted corroborated AI rule for the POC

Status: accepted for this POC by the owner on 30 October 2026. The owner selected corroborated indicators in this chat. The independent-receipt-identity requirement is replaced for this bounded POC rule; statistical qualification and write rollout remain separate gates.

The proposed rule is limited to an enrolled own-mailbox Microsoft 365/Claude route. Require complete supported-field inspection, the exact known Office365 MCP declaration, an authenticated successful Exchange Send event for the enrolled Claude application, matching tenant/mailbox/Internet Message-ID and send time, a current verified-publisher pin, complete audit query pagination, and no observed collision, conflict, source failure or revocation. Generic Gmail API traces, arbitrary AI-looking headers, writing style and normal browser sends never produce AI Agent under this rule. External senders without the enrolled audit source remain outside its qualified coverage.

The label would mean **corroborated AI-agent indicators under this POC policy**. It would not claim cryptographic or provider-native proof that the audit item and received copy are the same item. A forged/copied Message-ID and declaration could defeat correlation if the independent collision/context checks cannot expose the copy. That residual false-positive risk must be disclosed, tested in Phase 4 and kept separate from measured accuracy claims. Independent numeric accuracy and controlled Outlook writes remain later gates.

The stricter alternative keeps the independently verified receipt-identity requirement and returns Unknown when that link is unavailable. Current Microsoft audit identifiers did not map to the known Graph items in the bounded probes; the received copy has a transport ID absent from the Sent copy. No additional grant or Azure resource is justified merely to assume those identifiers are equivalent.

Either choice remains detection only. No email is sent, drafted, routed or approved by AgentTrace, and no category write is enabled here.
