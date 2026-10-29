"""Certificate assertions from the Windows user key store; tokens remain in memory."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from uuid import UUID

import msal  # type: ignore[import-untyped]

from .authorization import AccessDenied


class CertificateTokenProvider:
    def __init__(self, tenant: str, client: str, thumbprint: str, signer: Path):
        UUID(tenant)
        UUID(client)
        if not re.fullmatch(r"[A-Fa-f0-9]{40}", thumbprint):
            raise ValueError("invalid_workload_certificate_reference")
        self._tenant = tenant
        self._client = client
        self._thumbprint = thumbprint
        self._signer = signer
        self._application = msal.ConfidentialClientApplication(
            client,
            authority="https://login.microsoftonline.com/" + tenant,
            client_credential={"client_assertion": self._assertion},
            enable_pii_log=False,
            instance_discovery=False,
        )

    def _assertion(self) -> str:
        try:
            result = subprocess.run(
                ["pwsh", "-NoProfile", "-File", str(self._signer), "-Operation", "Sign"],
                input=json.dumps(
                    {"tenant": self._tenant, "client": self._client, "thumbprint": self._thumbprint}
                ),
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=30,
                shell=False,
                check=False,
            )
            if result.returncode or result.stdout.count(".") != 2:
                raise AccessDenied("workload_credential_unavailable")
            return result.stdout.strip()
        except Exception:
            raise AccessDenied("workload_credential_unavailable") from None

    def token(self, resource: str, *, force_refresh: bool = False) -> str:
        allowed = {
            "https://graph.microsoft.com",
            "https://storage.azure.com",
            "https://vault.azure.net",
            "https://api.loganalytics.io",
            "api://" + self._client,
        }
        if resource not in allowed and not re.fullmatch(r"api://[0-9a-fA-F-]{36}", resource):
            raise AccessDenied("workload_token_resource_denied")
        try:
            result = self._application.acquire_token_for_client(
                scopes=[resource + "/.default"], force_refresh=force_refresh
            )
            token = result.get("access_token")
            if not isinstance(token, str) or not token:
                raise AccessDenied("workload_token_unavailable")
            return token
        except Exception:
            raise AccessDenied("workload_token_unavailable") from None
