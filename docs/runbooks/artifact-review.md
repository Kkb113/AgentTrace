# Acquire and reproduce model/data artifacts

1. Obtain an approved source and usage rights before download. Run acquisition in an approved build/research environment, never in message-processing runtime. Keep files in private storage or ignored work/artifacts.
2. Freeze separate immutable source commits/revisions for research code, weights, tokenizer, dataset and calibration. Record original URLs, acquisition time, owner, configuration and license texts. Compute SHA-256 over the actual bytes and over each saved license/permission document. A repository license does not automatically license all model weights or datasets.
3. Review custom code and dependencies. Do not enable remote model code or pickle-based weight loading. Prefer reviewed safetensors and offline tokenizer/configuration files. Confirm the proposed model fits the accepted CPU/time budget.
4. Write and validate an ArtifactComponent record per component, with state verified only after revision/hash/rights evidence exists. Store an immutable/versioned private manifest beside the artifacts and commit only safe metadata after disclosure review. Check that the raw artifact is ignored and absent from git ls-files.
5. Reproduce in a fresh environment: verify every component hash, approved root, license evidence, normalization, score direction, calibration and threshold before inference. Version decisions with all these references. A changed component requires revalidation.
6. Enforce the seven/thirty-day pilot retention policy for raw mail/decisions independently of licensed research assets. Never train on pilot mail or upload it to a public detector. Publish only aggregate, reviewed experiment results.

No real model or dataset has been acquired by the foundation. Synthetic test artifact bytes exercise integrity checks only and are never described as a trained detector.
