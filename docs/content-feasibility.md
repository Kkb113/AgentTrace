# Bounded content-detection experiment

Protocol version 1.0, 28 October 2026. Status: defined; model comparison not yet run, consistent with the initial feasibility stage. Primary agent evidence work has priority.

Allocate at most ten engineer-days and forty CPU-hours initially, with zero GPU hours and zero paid detector/API calls. This is an engineering allocation in the accepted plan, not a booked staffing contract or a claim that datasets already exist. Use existing local CPU capacity first; cloud-equivalent cost is modeled in `azure-cost-baseline.md`. At the limit, publish results and classify the scorer as qualified or experimental. Content recall does not block independently qualified agent detection.

First compare [Fakespot RoBERTa-base](https://huggingface.co/fakespot-ai/roberta-base-ai-text-detection-v1) and [Desklib v1.01](https://huggingface.co/desklib/ai-text-detector-v1.01), subject to pinned license/weight/custom-code review. Benchmark Fast-DetectGPT or Binoculars only if added value and memory/runtime fit this budget. No customer mail is uploaded to public demos. No model or benchmark has been downloaded or executed by this protocol document.

## Data acquisition

Start with at least 300 documented policy negatives and 300 documented positives for development, with all four positive families represented: copied drafts, substantial rewriting, English translation, and mixed passages. The numbers are acquisition targets, not an existing corpus. Include original human business mail with permitted use and credible history, basic-correction controls, formal templates, non-native English and short replies. The project owner prepares synthetic agent/assistant examples outside AgentTrace; authorized writers provide genuine human originals and record provenance. Confirm usage rights before acquisition.

Use permitted RAID/DetectRL assets only as supplements, with separate data-license and leakage checks. Public historical essays or a detector's own training corpus cannot stand in for a current business-email holdout. Labels and scenario identifiers are held separately from model inputs. Record provider/version only when actually exposed. Never turn a model paraphrase into a human negative.

Reserve writer/thread/template/prompt-family/time-separated training, calibration and locked evaluation sets. Hold out a generator family or version and domain. Build a corpus manifest of record hashes, rights, independent creation history, family, length, split and label reviewer. Do not duplicate variations of the same template to inflate sample sizes.

## Evaluation and promotion

1. Freeze extraction, eligibility, score direction, selected model revisions, aggregation and thresholds before inspecting holdout labels.
2. Disable generation provenance for copy/paste evaluation. Run both models on identical body regions; report scores, latency, memory, unknowns and errors.
3. Measure confusion matrices, precision/recall intervals, false positives, all-length/eligible-only coverage, grammar-only error, subgroups and unfamiliar generators. Keep unknown positives as misses in overall recall.
4. The initial advisory-flag budget is a one-sided 95% upper false-positive bound of 1%, with 0.1% a stretch target. Zero errors over 300 independent negatives is sufficient for the former; 3,000 for the latter. Samples must represent each population actually claimed. Correct for correlation when applicable.
5. Seek 60% eligible recall, 50% readable-English coverage and 30% all-length recall as research goals. Failure is reported rather than concealed. Poor or underpowered performance leaves real scores in an explicitly experimental investigator view, not ordinary asserted-AI flags.
6. No score changes the agent finding. Model errors/timeouts yield unknown and cannot stall the attribution queue. Prefer CPU and small models; optional fine-tuning needs its own justified experiment.

Deliver the corpus manifest, model/license records, benchmark commands, predictions, model card, calibration artifact, costs and qualified-or-experimental decision. Actual independent labeling and content scoring remain later implementation work; this stage supplies a concrete, bounded path to them.
