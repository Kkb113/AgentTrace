# Contributing

Keep the two detection findings independent. Runtime packages must not send mail, manage approvals, operate an agent, or download a model while processing a message. Use descriptive filenames without implementation-phase numbers.

Start with the [local runbook](docs/runbooks/local-development.md). Before a PR, run the shared quality, security, infrastructure, integration and guard-controls gates. Commit generated schemas/requirements with their sources. Model/data acquisition needs separate pinned component hashes and rights evidence; no real mail, tokens, tenant identifiers, weights or datasets enter Git.

Use a `codex/` feature branch and a PR with the problem, final behavior, tests and material limitations. Main requires the recorded CI checks. Do not bypass a failing gate, suppress a vulnerability without a reviewed decision, lower a detection threshold to make a fixture pass, or count authored fixtures as independent accuracy evidence. Preserve unrelated user changes such as client workbooks.
