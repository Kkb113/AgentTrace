"""Guard the foundation's narrow import and network surface using the Python AST."""

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOWED_IMPORTS = {
    "__future__",
    "argparse",
    "collections",
    "contextlib",
    "dataclasses",
    "datetime",
    "fcntl",
    "hashlib",
    "json",
    "msvcrt",
    "os",
    "pathlib",
    "sqlite3",
    "sys",
    "time",
    "typing",
    "urllib",
    "uuid",
    "pydantic",
    "agenttrace_feasibility.validation",
    "agenttrace_foundation.workload_identity",
    "agenttrace_ingestion.transport",
}


def main() -> int:
    issues = []
    for path in sorted((ROOT / "src/agenttrace_outlook").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            imports: list[str] = []
            if isinstance(node, ast.Import):
                imports = [alias.name for alias in node.names]
            if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                imports = [node.module]
            for name in imports:
                if name not in ALLOWED_IMPORTS and name.split(".")[0] not in ALLOWED_IMPORTS:
                    issues.append(
                        {"file": path.name, "code": "unexpected_import", "line": node.lineno}
                    )
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "request"
            ):
                if (
                    path.name != "reader.py"
                    or not node.args
                    or not isinstance(node.args[0], ast.Constant)
                    or node.args[0].value != "GET"
                ):
                    issues.append(
                        {
                            "file": path.name,
                            "code": "non_read_network_operation",
                            "line": node.lineno,
                        }
                    )
    print(json.dumps({"outlook_boundary_issues": issues}, sort_keys=True))
    return int(bool(issues))


if __name__ == "__main__":
    raise SystemExit(main())
