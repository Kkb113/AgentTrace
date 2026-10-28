"""Validate a detection decision without printing message fields or raw input."""

import argparse
from pathlib import Path

from agenttrace_contracts import DetectionDecision
from pydantic import ValidationError


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    try:
        if args.path.stat().st_size > 1024 * 1024:
            return 1
        DetectionDecision.model_validate_json(args.path.read_bytes())
    except (OSError, ValidationError):
        print("Contract validation failed")
        return 1
    print("Contract valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
