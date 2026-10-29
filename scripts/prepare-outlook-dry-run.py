"""Create fictional, metadata-only inputs for the standalone foundation demonstration."""

import argparse
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from agenttrace_outlook.config import RuntimeConfig
from agenttrace_outlook.contracts import FixtureBatch, Observation, Scope


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    directory = args.directory.resolve()
    directory.mkdir(parents=True, exist_ok=False, mode=0o700)
    scope = Scope(tenant_id=UUID(int=1), mailbox_id=UUID(int=2))
    now = datetime.now(UTC)
    config = RuntimeConfig(scope=scope, state_directory=str(directory / "state"))
    fixture = FixtureBatch(
        synthetic=True,
        observations=(
            Observation(
                scope=scope,
                message_id="fictional-message-001",
                source_version="version-001",
                observed_at=now,
                received_at=now,
                inspection_complete=True,
                source_digest="a" * 64,
            ),
        ),
    )
    for name, value in (("runtime.json", config), ("observations.json", fixture)):
        (directory / name).write_text(
            value.model_dump_json(indent=2) + "\n", encoding="utf-8", newline="\n"
        )
    print("Fictional configuration and observations prepared; no mailbox connection or mutation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
