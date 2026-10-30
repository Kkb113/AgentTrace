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
    "random",
    "agenttrace_feasibility.validation",
    "agenttrace_feasibility.capabilities",
    "subprocess",
    "re",
    "email",
    "math",
    "tempfile",
    "base64",
    "hmac",
    "secrets",
    "cryptography",
    "agenttrace_foundation.workload_identity",
    "agenttrace_foundation.authorization",
    "agenttrace_ingestion.transport",
    "agenttrace_ingestion.contracts",
}


def main() -> int:
    issues = []
    for path in sorted((ROOT / "src/agenttrace_outlook").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if path.name == "audit_source.py":
            roots = [
                node.value.value
                for node in tree.body
                if isinstance(node, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "ROOT" for t in node.targets)
                and isinstance(node.value, ast.Constant)
            ]
            if roots != ["https://graph.microsoft.com/v1.0/security/auditLog/queries"]:
                issues.append({"file": path.name, "code": "audit_root_modified"})
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
                post = bool(
                    node.args
                    and isinstance(node.args[0], ast.Constant)
                    and node.args[0].value == "POST"
                )
                if post:
                    body = next((kw.value for kw in node.keywords if kw.arg == "body"), None)
                    keys = (
                        {key.value for key in body.keys if isinstance(key, ast.Constant)}
                        if isinstance(body, ast.Dict)
                        else set()
                    )
                    if (
                        path.name != "audit_source.py"
                        or len(node.args) < 2
                        or not isinstance(node.args[1], ast.Name)
                        or node.args[1].id != "ROOT"
                        or keys
                        != {
                            "displayName",
                            "filterStartDateTime",
                            "filterEndDateTime",
                            "recordTypeFilters",
                            "operationFilters",
                            "userPrincipalNameFilters",
                        }
                    ):
                        issues.append(
                            {
                                "file": path.name,
                                "code": "unsafe_analytical_post",
                                "line": node.lineno,
                            }
                        )
                if (
                    path.name not in {"reader.py", "audit_source.py"}
                    or not node.args
                    or not isinstance(node.args[0], ast.Constant)
                    or node.args[0].value
                    not in ({"GET", "POST"} if path.name == "audit_source.py" else {"GET"})
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
