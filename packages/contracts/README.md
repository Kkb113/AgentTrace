# Detection contracts

`agenttrace_contracts` defines strict Pydantic models for exactly two independent findings, decisions and reference-only jobs. `schemas/` holds generated JSON Schema. Run `python scripts/export-contracts.py --check` to catch drift. Unknown flags are null. An experimental content score cannot be promoted to a positive or change an agent finding.
