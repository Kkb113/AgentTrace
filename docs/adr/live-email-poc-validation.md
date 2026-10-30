# Owner-operated live-email validation for the POC

Accepted scope revision, 30 October 2026: the owner selected testing with actual emails sent manually and through existing agents. Phase 4 no longer requires an external corpus, independent curator, separate review team or thousands of examples before this controlled POC can proceed. This product detects send actions, not AI-written text.

Test operators record how each synthetic message was actually sent, then compare the received message's decision and technical evidence. Operator action records are test ground truth only: the classifier must not use the expected label, subject marker, filename or writing style as a prediction signal. Using the same wording for manual and agent sends is a useful control. No prose authorship judgment is required.

The revised POC exits require actual manual/agent examples through the supported Outlook pipeline, explainable reproducible results, conservative adversarial/source controls and clear coverage limits. Known manual cases must not receive an AI badge. Unavailable or conflicting AI evidence remains Unknown; Human-capable retains the previously approved normal-client compatibility meaning.

Controlled self-tests establish that the supported workflow works on the tested cases. They do not establish population-wide 0.1% false-positive or 99% recall claims. G1/G2 remain future statistical production-qualification targets. The existing accuracy/curator tooling remains optional for that purpose and is not a prerequisite for the current POC. Historical reports retain their original scope and results.

The approved data boundary remains synthetic, non-sensitive test email. AgentTrace still only detects: operators send through Outlook, Gmail or their existing agent tools; AgentTrace never sends, drafts or approves email. This revision creates no permission, Azure resource, category or live write capability. Category permission/setup and safe writes remain subsequent phases.
