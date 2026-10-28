# Reviewed artifacts outside Git

Status: procedure and enforcing schemas implemented; no model/data artifact acquired.

Research code, weights, tokenizer, dataset and calibration each have separate revision, SHA-256, SPDX license and license-evidence hash fields. A verified component requires all fields and an explicit rights review. Unacquired candidates have null/absent hashes rather than invented versions. Runtime accepts approved local files only, checks containment and content hash, requires safetensors for weights, and forbids trust_remote_code. No model download occurs while processing a message.

The UV lock records Python package artifacts and hashes; it is separate from model/data provenance. Public candidate locations are a research catalog, not an endorsement or completed acquisition. Follow the artifact review runbook before experiments.
