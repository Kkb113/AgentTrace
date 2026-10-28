"""Generate traceable allowed/denied read-only Graph requests for live log testing."""

import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request, build_opener
from uuid import uuid4

from agenttrace_foundation.mail_reader import NoRedirect
from agenttrace_foundation.workload_identity import CertificateTokenProvider

ROOT = Path(__file__).resolve().parents[1]


def main():
    baseline = ROOT / "work/private/secure-access"
    config = json.loads(
        (baseline / "sandbox-settings.private.json").read_text(encoding="utf-8-sig")
    )
    identities = json.loads((baseline / "workload-identities.private.json").read_text())
    runtime = json.loads((ROOT / "work/private/mail-ingestion/runtime.private.json").read_text())
    folder = runtime["enrollment"]["folder_ids"][0]
    root = "https://graph.microsoft.com/v1.0/users/"
    requests = [
        (
            "allowed_synthetic_folder",
            "mail-collector",
            root
            + config["mailbox_id"]
            + "/mailFolders/"
            + quote(folder, safe="")
            + "/messages?"
            + urlencode({"$select": "id", "$top": "1"}),
            200,
            True,
        ),
        (
            "denied_control_mailbox",
            "mail-collector",
            root
            + config["control_mailbox_id"]
            + "/messages?"
            + urlencode({"$select": "id", "$top": "1"}),
            403,
            True,
        ),
        (
            "excluded_application",
            "access-test",
            root + config["mailbox_id"] + "/messages?" + urlencode({"$select": "id", "$top": "1"}),
            403,
            False,
        ),
    ]
    observations = []
    opener = build_opener(NoRedirect())
    for label, alias, url, expected, logged in requests:
        identity = identities[alias]
        provider = CertificateTokenProvider(
            config["tenant"],
            identity["application"]["appId"],
            identity["certificate"]["thumbprint"],
            ROOT / "scripts/manage-workload-certificate.ps1",
        )
        client_request = str(uuid4())
        headers = {
            "Authorization": "Bearer " + provider.token("https://graph.microsoft.com"),
            "client-request-id": client_request,
            "return-client-request-id": "true",
            "Prefer": 'IdType="ImmutableId"',
        }
        request = Request(url, headers=headers, method="GET")
        start = datetime.now(UTC).isoformat()
        try:
            with opener.open(request, timeout=20) as response:
                status, response_headers = response.status, response.headers
                response.read(4096)
        except HTTPError as error:
            status, response_headers = error.code, error.headers
        if status != expected:
            raise RuntimeError("read_only_probe_permission_expectation_failed")
        observations.append(
            {
                "label": label,
                "client_request_id": client_request,
                "request_id": response_headers.get("request-id"),
                "client_id": identity["application"]["appId"],
                "time": start,
                "http_status": status,
                "expected_logged": logged,
            }
        )
    path = ROOT / "work/private/graph-activity/read-only-probes.private.json"
    if path.exists():
        archive = path.parent / "earlier-read-only-probes.private.json"
        earlier = json.loads(archive.read_text()) if archive.exists() else []
        earlier += json.loads(path.read_text())
        archive.write_text(json.dumps(earlier, indent=2))
    path.write_text(json.dumps(observations, indent=2))
    print(
        json.dumps(
            {
                "read_only_probes": len(observations),
                "positive_and_negative_permissions_match": True,
                "email_mutations": 0,
            }
        )
    )


if __name__ == "__main__":
    main()
