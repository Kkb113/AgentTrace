"""Check the detection-only package, route and artifact boundaries."""

import ast
import json
from pathlib import Path

from agenttrace_contracts import DetectionFindings

from agenttrace_foundation.api import create_app
from agenttrace_foundation.artifacts import ArtifactComponent
from agenttrace_ingestion.api import create_app as create_ingestion_app

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_MODULES = {
    "smtplib",
    "openai",
    "anthropic",
    "langchain",
    "langgraph",
    "crewai",
    "autogen",
}
FORBIDDEN_CALLS = {
    "send_mail",
    "send_email",
    "sendMail",
    "send_message",
    "create_draft",
    "approve_send",
}


def main() -> int:
    assert set(DetectionFindings.model_fields) == {"agent_send_attribution", "content_assessment"}
    for path in [
        *(ROOT / "packages").rglob("*.py"),
        *(ROOT / "src/agenttrace_foundation").rglob("*.py"),
        *(ROOT / "src/agenttrace_ingestion").rglob("*.py"),
    ]:
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                assert all(
                    alias.name.split(".")[0] not in FORBIDDEN_MODULES for alias in node.names
                )
            elif isinstance(node, ast.ImportFrom):
                assert (node.module or "").split(".")[0] not in FORBIDDEN_MODULES
            elif isinstance(node, ast.Call):
                name = (
                    node.func.attr
                    if isinstance(node.func, ast.Attribute)
                    else node.func.id
                    if isinstance(node.func, ast.Name)
                    else ""
                )
                assert name not in FORBIDDEN_CALLS
    schema = create_app().openapi()
    assert set(schema["paths"]) == {"/health/live", "/health/ready", "/v1/decisions/{decision_id}"}
    assert all(set(methods) == {"get"} for methods in schema["paths"].values())
    ingestion = create_ingestion_app(None, None).openapi()
    assert {path: set(methods) for path, methods in ingestion["paths"].items()} == {
        "/v1/notifications": {"post"},
        "/v1/ingestion/sources/{source_ref}": {"get"},
    }
    catalog = json.loads((ROOT / "config/artifact-catalog.json").read_text())
    for entry in catalog["components"]:
        ArtifactComponent.model_validate(entry)
    print("Detection-only routes, packages and artifact contracts passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
