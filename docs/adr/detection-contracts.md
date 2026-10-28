# Independent detection contracts

Status: accepted implementation decision within the owner-approved scope.

Use one Python distribution with separate domain packages and process hosts. The two findings are agent_send_attribution and content_assessment. Strict schemas reject extra fields, inconsistent status/flag pairs, non-finite content scores and statistical positives without qualified calibration. Agent findings have no content score input. Unknown is null. Generated JSON Schema is reviewed in Git and checked against the Pydantic source.

The source distribution retains the feasibility entry point for reproducible historical evidence. Product processes import only the read-only evidence replay boundary, not its operator authentication tools. API/UI scaffolds do not imply that later authentication, mailbox ingestion, statistical scoring or presentation milestones are complete.
