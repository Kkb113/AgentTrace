# Repository foundation review

Status: implemented and locally validated; fresh installation passed; hosted PR checks are being completed. The machine-readable exit record is config/foundation-exits.json.

## Delivered boundaries

The foundation has typed domain packages for contracts, attribution, read-only evidence, private content scoring, inclusion provenance and offline text extraction. Exactly two independent findings are exposed. Strict contracts reject a positive agent without evidence, inconsistent flags and unqualified positive statistical content scores. Generated schemas and hash-pinned runtime/build/development exports are checked for drift.

Local services comprise digest-pinned PostgreSQL 17.11, a FastAPI GET API and separate attribution/content processes. The development queue has concurrent claims, scoped receipts, visibility expiry, retries, poison state and payload-aware idempotency. Result persistence and acknowledgement are atomic. A real TCP test queues an authored reference, processes it in the separate worker and retrieves the decision through the API. Synthetic fixtures are not independent accuracy evidence.

The content process remains healthy in standby without a scorer and does not acknowledge content work. Actual statistical scoring, production authentication, mailbox collection, UI implementation and Azure Queue parity remain later work. The dashboard/add-in directories document their future boundaries; no UI is claimed now. Production configuration is refused and network access is limited to the local synthetic stack.

## Validation

The reviewed local run passed all five shared gates. Pytest reported 90 unit/security tests plus 52 subtests and eight integration/end-to-end tests. The JUnit count is 150 including those subtests. Strict typing, formatting, schema/requirements drift, source boundaries, secret/privacy checks, license review and dependency vulnerability audit passed. All six Bicep modules and their no-provisioning parameter file compiled. No Azure resource was provisioned.

The negative controls invoke the real validation commands: an invalid contract, a failing pytest file and a high-entropy nonfunctional synthetic credential each exit 1. The controls gate succeeds only when all three are rejected. These fixtures are created under ignored work storage and are not committed or uploaded.

Testing found and fixed Docker image ordering, Docker Desktop internal-network port forwarding, the test-client dependency migration and a credential-bearing database error trace. The affected generated local database password was rotated, driver exceptions were sanitized, and a regression test verifies that credentials cannot appear through that error path. Worker networks remain internal; only API/database get a loopback-published access bridge.

A pre-commit Git-index export was independently installed into a fresh repository/virtual environment without private state. All gates and the eight-test real database/TCP suite passed with a new database and generated credential. See docs/evidence/foundation-clean-install.json. Hosted CI will additionally verify a genuine Git checkout.

## CI and access

Azure project creation returned TF50309 for missing Create new projects permission. The owner explicitly selected GitHub Actions for active PR checks and equivalent Azure Pipelines YAML. Both definitions invoke the same gate scripts. Actions are pinned by commit and validator binaries by release SHA-256. Jobs have contents:read, no Azure token or secret, and no persisted checkout credentials. Azure YAML is retained but an Azure run is not claimed. The optional future WIF what-if template is main-only and requires a separately approved protected connection.

Native secret scanning and push protection are enabled. Required-check enforcement and the hosted PR results will be recorded after the actual runs. No Microsoft mailbox permission, Entra application or Azure role was created. The old feasibility reader stays retired. Existing client workbook changes remain excluded from this implementation.

## Artifact handling

The catalog records research code, weights, tokenizer, dataset and calibration separately. No model/data artifact has been acquired; no revision, hash or license is invented. Verified components require immutable revision, byte hash and separate rights-evidence hash; local loading verifies containment/hash and safetensors format. Raw assets remain outside Git and runtime model downloads are absent. The artifact review runbook records acquisition, rights, calibration, disclosure and reproduction obligations.

Decision expiry is checked at thirty days; physical purge, backups and retained raw-evidence lifecycle are later milestones. Compile-only infrastructure validation does not authorize provisioning or production use. Release false-positive/recall/content criteria remain unmeasured.
