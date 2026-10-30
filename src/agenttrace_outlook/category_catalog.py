"""Exact-mailbox master-category adapter with a distinct setup-only POST path."""

from pathlib import Path
from typing import Any, Literal
from urllib.parse import parse_qs, urlsplit

from agenttrace_foundation.authorization import AccessDenied
from agenttrace_foundation.workload_identity import CertificateTokenProvider
from agenttrace_ingestion.contracts import IngestionError
from agenttrace_ingestion.transport import MicrosoftTransport

from .category_contracts import PRESETS, CategorySettings, Label, MasterCategory
from .errors import OutlookError, SourceError


class CategoryCatalog:
    def __init__(
        self, settings: CategorySettings, transport: Any, *, identity: Literal["writer", "setup"]
    ):
        if identity == "setup" and settings.setup_identity is None:
            raise OutlookError("category_setup_identity_unavailable")
        self.settings, self.transport, self.identity = settings, transport, identity
        self.base = (
            "https://graph.microsoft.com/v1.0/users/"
            + str(settings.scope.mailbox_id)
            + "/outlook/masterCategories"
        )

    def inventory(self) -> tuple[MasterCategory, ...]:
        url = self.base + "?$select=id,displayName,color&$top=100"
        seen = set()
        items = []
        try:
            while True:
                if url in seen:
                    raise SourceError("category_pagination_loop")
                self._validate_page(url)
                seen.add(url)
                result = self.transport.request("GET", url)
                rows = result.get("value")
                if not isinstance(rows, list):
                    raise SourceError("category_inventory_invalid")
                for row in rows:
                    items.append(
                        MasterCategory(
                            id=row["id"], display_name=row["displayName"], color=row["color"]
                        )
                    )
                if len(items) > 1000:
                    raise SourceError("category_inventory_limit_exceeded")
                if not result.get("@odata.nextLink"):
                    break
                url = result["@odata.nextLink"]
            if len({c.id for c in items}) != len(items):
                raise SourceError("category_inventory_ambiguous")
            return tuple(items)
        except IngestionError as error:
            raise SourceError(
                error.code, retryable=error.retryable, retry_after=error.retry_after
            ) from None
        except AccessDenied:
            raise SourceError("category_authentication_unavailable") from None
        except (ValueError, TypeError, KeyError, AttributeError):
            raise SourceError("category_inventory_invalid") from None

    def _validate_page(self, url: str) -> None:
        if not isinstance(url, str) or len(url) > 32768:
            raise SourceError("category_cursor_out_of_scope")
        parsed, base = urlsplit(url), urlsplit(self.base)
        query = parse_qs(parsed.query, keep_blank_values=True)
        if (
            parsed.scheme != "https"
            or parsed.netloc != base.netloc
            or parsed.path != base.path
            or parsed.fragment
            or set(query) - {"$select", "$top", "$skiptoken", "$skip"}
            or any(len(v) != 1 or not v[0] for v in query.values())
            or ("$select" in query and query["$select"] != ["id,displayName,color"])
            or ("$top" in query and query["$top"] != ["100"])
        ):
            raise SourceError("category_cursor_out_of_scope")

    def create(self, label: Label) -> MasterCategory:
        if self.identity != "setup" or self.settings.setup_identity is None or label not in PRESETS:
            raise OutlookError("category_provisioning_not_allowed_for_runtime")
        try:
            row = self.transport.request(
                "POST", self.base, body={"displayName": label, "color": PRESETS[label]}
            )
            result = MasterCategory(
                id=row["id"], display_name=row["displayName"], color=row["color"]
            )
            if result.display_name != label or result.color != PRESETS[label]:
                raise SourceError("created_category_definition_mismatch")
            return result
        except IngestionError as error:
            # A failed/timeout POST is ambiguous. Never retry or adopt its name automatically.
            raise SourceError(error.code, retryable=False) from None
        except AccessDenied:
            raise SourceError("category_authentication_unavailable") from None
        except (ValueError, TypeError, KeyError):
            raise SourceError("created_category_response_invalid") from None


def certificate_catalog(
    settings: CategorySettings, identity: Literal["writer", "setup"]
) -> CategoryCatalog:
    credential = settings.writer_identity if identity == "writer" else settings.setup_identity
    if credential is None:
        raise OutlookError("category_setup_identity_unavailable")
    provider = CertificateTokenProvider(
        str(settings.scope.tenant_id),
        str(credential.client_id),
        credential.certificate_thumbprint,
        Path(__file__).resolve().parents[2] / "scripts/manage-workload-certificate.ps1",
    )
    return CategoryCatalog(
        settings,
        MicrosoftTransport(
            lambda *, force_refresh=False: provider.token(
                "https://graph.microsoft.com", force_refresh=force_refresh
            )
        ),
        identity=identity,
    )
