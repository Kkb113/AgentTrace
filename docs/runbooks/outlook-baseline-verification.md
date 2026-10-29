# Verify the Outlook-native baseline

These commands validate Phase 0 requirements and read existing synthetic evidence. They do not start the future production runner or grant annotation access.

```powershell
uv sync --frozen --all-groups
uv run python scripts/verify-outlook-baseline.py
uv run python -m pytest tests/test_outlook_baseline.py tests/test_mail_monitor.py tests/test_audit_capture.py -q
```

To regenerate the reviewed schema after an intentional versioned contract change, use `scripts/verify-outlook-baseline.py --export-schema`, inspect the diff and rerun validation. Do not change the frozen profile to enable category writes; Phase 1 introduces separate runtime configuration and Phase 5 validates write access.

## Fresh read-only feasibility check

Use the already approved operator identities in protected `work/private/secure-access/`. Do not re-create or grant access merely because a probe fails. Existing certificates must be accessible under the current Windows runtime account. The inspector requires operator Azure CLI directory-read access for existing assignment inventory, a scoped mail reader and the existing audit reader. It never runs in PR CI.

Prepare a protected private locator JSON with a `cases` array of one to three entries. Each includes `case_ref`, `expected_subject`, `owner_reported_actor` and either `message_id` or `internet_message_id`. Only owner-prepared `AgentTrace demo ` or `AgentTrace synthetic test:` subjects are allowed. For the existing Outlook audit case, include its saved `audit_query_id`; no new search is created. Never commit the locator, actual IDs or raw replies. Locators select source records and are not supplied to the detector as truth.

```powershell
uv run python scripts/inspect-outlook-baseline.py `
  --locators work/private/outlook-baseline-locators.private.json `
  --private-output work/private/outlook-baseline-new-capture `
  --report work/reports/outlook-baseline-new-inspection.json
```

The private output must be new. The command validates selected subjects, source retention, mailbox/account scope, the saved query's exact actor/time/operation filters, pagination completeness and absence of unexpected Entra mail-write/send grants. Folder inventory is deliberately bounded; crossing the bound fails rather than claiming completeness. Current Entra grants are not a complete Exchange RBAC assessment; allowed/denied Graph reads supplement the historical scoped assignment record. Category-write and master-category collisions are untested until their own phase.

The combined private packet expires at the earliest selected message's received time plus seven days, or seven days from observation, whichever is sooner. Follow the exact-file cleanup process; do not reset original source deadlines when reusing captures. Returned public summaries contain aliases, booleans, role names and capture hashes, not addresses/headers/tokens. Review the summary and the privacy gate before copying it to docs/evidence.

If the check fails, the process returns nonzero and a sanitized error. Safe exception-type/frame diagnostics can be written in the private output; raw upstream error text is never emitted. A source failure cannot imply Human. Fix configuration/availability within existing authorization or record an actual source gap; do not broaden permissions automatically.

## Claims and next steps

The [baseline review](../outlook-production-baseline.md) records current facts and dependencies. Human is the owner's inferred-manual policy after complete observable inspection, not proof of a person at the device. Its false-human behavior on untagged/browser agents remains to be measured. The default demo's two labels are experimental and cannot enter the future category writer. New runtime/durable processing, qualified rules, category setup, safe writes and unattended operation remain Phases 1–9.
