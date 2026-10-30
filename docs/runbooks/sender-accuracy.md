# Sender accuracy and adversarial validation

This is the active sender-only workflow for the Outlook rules. The older uncommitted `agenttrace_evaluation` tools target a retired detector/content design and are preserved separately. Use `scripts/validate-sender-accuracy.py`; no web application, Microsoft call, email send or category write is part of this tool.

## Current readiness

The software can inspect an imported study, check reviews/rights/retention and leakage, replay the actual rule functions, compute exact confidence bounds, export developer inputs, encrypt a curator holdout and consume a code-bound authorization once. Authored control drills validate these mechanisms. Actual independent qualification requires real source records, independent action reviews, representative samples and separately controlled curator access. Existing owner examples and relayed judgments about prose do not meet that requirement.

No production accuracy or category-write gate is enabled by a software test. A low-volume pilot remains unqualified even if its observed decisions are correct. The [Phase 4 review](../sender-accuracy-review.md) records the exact completed work and outstanding evidence.

## Prepare collection and freeze

```powershell
uv run python scripts/validate-sender-accuracy.py prepare-collection --output work/private/sender-accuracy/collection
uv run python scripts/validate-sender-accuracy.py fingerprint --output work/private/sender-accuracy/freeze.json
```

Outputs must be new. The collection directory contains instructions, a blank collection CSV, schemas and code/policy fingerprints; it contains no invented emails, labels, reviewers or signatures. The curator assembles `dataset.json` using `sender-accuracy-dataset.schema.json`; `DetectorPacket` uses `sender-replay-packet.schema.json`. Source packets are selected metadata/header snapshots and actual audit/publisher/copy captures. `query_id`, scoped succeeded query, full pagination, current publisher pins and copy context are rechecked; a supplied `authenticated=true` property is rejected. Offline JSON cannot establish source authenticity: the independent curator must verify original collector/system custody and exact asset hashes. Legitimate source executor fields remain evidence; separate ground-truth labels never reach the detector.

Reviews bind input, action and rights hashes. Their attestation JSON is the exact ActionReview record excluding the `attestation` asset itself. An independent source-quality review is sufficient for a credible documented action; conflicting reviews need a third independent adjudication. Missing, expired or inconsistent history remains quarantined. Synthetic EML bodies are read privately only for grouping/leakage, never by the detector. This is explicitly supplied evaluation data, not live body collection.

The dataset lists actual sender/workflow/thread/template/source/independence groups, routes, actors, source families and prepared times. The tool verifies chronological disjoint splits, duplicated input/action/provider IDs, exact normalized text and bounded shingle-similarity candidates. Similarity is a screening heuristic, not proof that no semantic paraphrase leaked; independent curator review remains necessary. Shared templates/text are conservatively clustered, retaining crossed actor pairs in their respective denominators. Repeated exports cannot manufacture sample size.

```powershell
uv run python scripts/validate-sender-accuracy.py inspect --dataset <curator-directory>/dataset.json --output <curator-directory>/inspection.json
uv run python scripts/validate-sender-accuracy.py export-development --dataset <curator-directory>/dataset.json --output <new-developer-directory>
uv run python scripts/validate-sender-accuracy.py run --dataset <new-developer-directory>/dataset.json --split development --output <new-private-report.json>
```

The normal runner refuses a manifest containing evaluation cases. Developers receive only the exported development/calibration subset and its assets. The curator retains originals and ground truth. Renaming a file or declaring a reviewer human does not establish external independence; actual appointment/source review/access evidence is still required.

## Curator-controlled holdout

Windows access inspection uses the already installed PowerShell 7 (`pwsh.exe`). The legacy Windows PowerShell host inherited incompatible module paths during the actual control drill; the implementation now uses PowerShell 7 explicitly and tests the real helper. No execution-policy or tenant-policy exception is applied.

`ActionReview.case_sha256` must equal `review_binding(case)` from `accuracy_contracts.py`. That binding covers route, source/population, grouping, times and source assets, excluding the separate reviewer records and proposed actor label. Changing cohort membership or a message asset after review invalidates the review; independent disagreements can still be preserved and adjudicated.

Run these under the independent curator's OS account. Use a source directory and key directory private to that curator, SYSTEM and administrators, and an archive directory separate from the key directory. Supply the actual developer account SID on Windows or UID on POSIX. The access helper reads OS ownership/ACLs; it never changes them or creates accounts. CurrentUser privileges and OS administrators remain trusted.

```powershell
uv run python scripts/validate-sender-accuracy.py create-key --output <curator-key-directory>/study.key
uv run python scripts/validate-sender-accuracy.py seal --dataset <curator-directory>/dataset.json --key <curator-key-directory>/study.key --developer-principal <developer-SID-or-UID> --output <curator-archive-directory>/study.json
uv run python scripts/validate-sender-accuracy.py grant --archive <curator-archive-directory>/study.json --key <curator-key-directory>/study.key --output <new-permit.json>
uv run python scripts/validate-sender-accuracy.py evaluate-locked --archive <curator-archive-directory>/study.json --permit <new-permit.json> --key <curator-key-directory>/study.key --receipts <curator-receipt-directory> --output <new-private-report.json>
```

AES-GCM authenticates frozen data and metadata; a one-hour HMAC grant binds archive, code and policy. Source expiry is checked before plaintext access. One atomic receipt consumes the dataset's evaluation even if a new grant/archive is created; a crash after consumption requires curator investigation, not a silent retry. The curator must protect and preserve that receipt directory. An administrator who can retrieve keys or delete receipts can defeat this boundary. The tool cannot prove deleted developer copies or an operator's human organizational role; curator custody evidence must address those facts.

`--control-drill` on `seal` exercises the encrypted workflow on authored/test data under one operator. Its resulting report always has `locked_access_verified=false` and `release_accuracy_qualified=false`. It cannot close the independent-access exit.

Exit codes: `0` successful engineering operation or qualified evaluation; `1` completed inspection/evaluation that remains invalid or unqualified; `2` input/authorization/runtime failure. An evaluation report returning 1 is an expected outcome for an underpowered control drill. Raw exceptions, paths, addresses, source records and key bytes are never printed.

## Metrics and interpretation

The schema allows up to 20,000 cases. File reads are bounded at 192 MiB, cumulative raw study inputs at 128 MiB and sealed plaintext at 128 MiB, allowing multi-thousand-message qualification cohorts with compact selected evidence. Oversized cohorts fail explicitly; the tool never samples away rows to meet a memory limit.

The [frozen policy](../../config/sender-accuracy-policy.json) preserves G1/G2: one-sided 95% exact agent FPR upper bound ≤0.1%, and ≥99% observed recall on ≥1,000 independent supported-route agent positives. Zero errors among 3,000 independent negatives is sufficient for the former bound. Limits use binomial-CDF inversion; see [NIST exact binomial limits](https://itl.nist.gov/div898/software/dataplot/refman2/auxillar/exacbino.htm). Correlation/selection bias can invalidate the binomial model; clustering and a credible sampling design remain necessary.

Every enabled AI-positive rule is assessed as a union. Non-agent negatives include ordinary automation. Unknown truth is excluded rather than assumed human; known agent Unknown/pending/Human-capable results are misses. Supported-route membership is checked against the frozen enrolled source scope, not selected because a prediction succeeded. Report all-path, supported-path, population, route, source and approval strata; a pooled bound does not qualify every subgroup.

Initial results use only frames available by observation +2 hours; late results use +24 hours and cannot overwrite initial misses. Future deadlines are not scored; stale captures and incomplete sources remain Unknown. A missing historical frame is not invented from a later successful read. The initial-window gates govern qualification; late results disclose delayed availability.

Human-capable measures client compatibility, not physical human identity. Browser-driven agents intentionally share that label and count as all-path agent misses. Source-unobservable conventional automation can share compatible observables too. Generic Gmail API use is not qualified AI attribution. The accepted unobservable copied-ID full replacement remains a counterexample, not a successfully rejected attack. No report establishes universal detection or independent forensic received-item identity.

Private raw assets, originals, encrypted archives and temporary exports share their original seven-day deadline; import/encryption does not restart retention. Reports have a thirty-day operational retention requirement. Read-time denial is implemented here; scheduled physical deletion, encrypted backup handling and supervision remain the later operational phase. No Azure resource or permission is needed for this offline work.
