"""Generate/check hash-pinned requirements consistently on Windows and Linux."""

import argparse
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    for filename, options in [
        ("requirements-runtime.txt", ["--no-dev"]),
        ("requirements-build.txt", ["--only-group", "build"]),
        ("requirements-development.txt", ["--all-groups"]),
    ]:
        result = subprocess.run(
            ["uv", "export", "--frozen", "--no-header", "--no-emit-project", *options],
            cwd=ROOT,
            capture_output=True,
            text=True,
            shell=False,
            check=True,
        )
        path = ROOT / filename
        if args.check:
            if not path.is_file() or path.read_text() != result.stdout:
                print("Stale requirements export: " + filename)
                return 1
        else:
            path.write_text(result.stdout, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
