"""Category ownership, constrained setup and no-op probes never enable classification writes."""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import timedelta
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from agenttrace_ingestion.contracts import IngestionError
from agenttrace_outlook.category_catalog import CategoryCatalog
from agenttrace_outlook.category_contracts import (
    PRESETS,
    CategorySettings,
)
from agenttrace_outlook.category_ownership import OwnershipStore, provision, verify_ownership
from agenttrace_outlook.category_preview import category_preview
from agenttrace_outlook.category_probe import CategoryPermissionProbe
from agenttrace_outlook.config import ReaderIdentity
from agenttrace_outlook.contracts import Decision
from agenttrace_outlook.errors import OutlookError
from agenttrace_outlook.sender_rules import evaluate, sha
from tests.unit.test_sender_rules import NOW, SCOPE, observation, snapshot


def settings(path: Path) -> CategorySettings:
    return CategorySettings(
        scope=SCOPE,
        control_mailbox_id=UUID(int=9),
        writer_identity=ReaderIdentity(client_id=UUID(int=10), certificate_thumbprint="a" * 40),
        setup_identity=ReaderIdentity(client_id=UUID(int=11), certificate_thumbprint="b" * 40),
        ownership_directory=str(path),
    )


class CatalogTransport:
    def __init__(self):
        self.rows = []
        self.calls = []
        self.fail_label = None
        self.lose_response = False
        self.cursor = None

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if method == "GET":
            result = {"value": list(self.rows)}
            if self.cursor:
                result["@odata.nextLink"] = self.cursor
            return result
        body = kwargs["body"]
        if body["displayName"] == self.fail_label:
            if self.lose_response:
                self.rows.append(
                    {"id": "ambiguous", "displayName": self.fail_label, "color": body["color"]}
                )
            raise IngestionError("source_network_unavailable", retryable=True)
        row = {"id": "category_" + str(len(self.rows)), **body}
        self.rows.append(row)
        return row


def provisioned(path):
    cfg = settings(path)
    transport = CatalogTransport()
    store = OwnershipStore(cfg)
    registry = provision(store, CategoryCatalog(cfg, transport, identity="setup"), NOW)
    store.close()
    return cfg, registry, transport


def test_setup_creates_exact_definitions_and_replay_never_recreates(tmp_path: Path) -> None:
    cfg, registry, transport = provisioned(tmp_path)
    assert [(c.category.display_name, c.category.color) for c in registry.categories] == list(
        PRESETS.items()
    )
    assert sum(c[0] == "POST" for c in transport.calls) == 3
    store = OwnershipStore(cfg)
    try:
        assert provision(store, CategoryCatalog(cfg, transport, identity="setup"), NOW) == registry
    finally:
        store.close()
    assert sum(c[0] == "POST" for c in transport.calls) == 3


@pytest.mark.parametrize("existing", ["AI Agent", "ai agent", "  AI  Agent ", "ＡＩ Agent"])
def test_user_owned_name_collision_blocks_all_creation_before_first_post(
    tmp_path: Path, existing: str
) -> None:
    cfg = settings(tmp_path)
    transport = CatalogTransport()
    transport.rows = [{"id": "user_category", "displayName": existing, "color": "preset9"}]
    store = OwnershipStore(cfg)
    try:
        with pytest.raises(OutlookError, match="unowned_category_name_conflict"):
            provision(store, CategoryCatalog(cfg, transport, identity="setup"), NOW)
    finally:
        store.close()
    assert all(c[0] == "GET" for c in transport.calls)
    assert transport.rows[0]["color"] == "preset9"


def test_unrelated_categories_survive_setup_unchanged(tmp_path: Path) -> None:
    cfg = settings(tmp_path)
    transport = CatalogTransport()
    personal = {"id": "personal", "displayName": "Personal", "color": "none"}
    transport.rows = [personal.copy()]
    store = OwnershipStore(cfg)
    try:
        provision(store, CategoryCatalog(cfg, transport, identity="setup"), NOW)
    finally:
        store.close()
    assert transport.rows[0] == personal
    assert not any(c[0] in {"PATCH", "DELETE"} for c in transport.calls)


def test_confirmed_partial_setup_resumes_from_pinned_ids(tmp_path: Path) -> None:
    cfg = settings(tmp_path)
    transport = CatalogTransport()
    transport.fail_label = "Human"
    store = OwnershipStore(cfg)
    try:
        with pytest.raises(OutlookError):
            provision(store, CategoryCatalog(cfg, transport, identity="setup"), NOW)
        assert len(store.load().categories) == 1
        transport.fail_label = None
        completed = provision(store, CategoryCatalog(cfg, transport, identity="setup"), NOW)
        assert (
            len(completed.categories) == 3 and completed.categories[0].category.id == "category_0"
        )
    finally:
        store.close()


def test_lost_post_response_never_adopts_an_unconfirmed_name(tmp_path: Path) -> None:
    cfg = settings(tmp_path)
    transport = CatalogTransport()
    transport.fail_label = "AI Agent"
    transport.lose_response = True
    store = OwnershipStore(cfg)
    try:
        with pytest.raises(OutlookError):
            provision(store, CategoryCatalog(cfg, transport, identity="setup"), NOW)
        transport.fail_label = None
        with pytest.raises(OutlookError, match="unowned_category_name_conflict"):
            provision(store, CategoryCatalog(cfg, transport, identity="setup"), NOW)
        assert store.load() is None
    finally:
        store.close()


@pytest.mark.parametrize("change", ["id", "display_name", "color", "missing"])
def test_definition_drift_or_replacement_cannot_be_silently_owned(
    tmp_path: Path, change: str
) -> None:
    cfg, registry, transport = provisioned(tmp_path)
    items = [c.category for c in registry.categories]
    if change == "missing":
        items.pop()
    else:
        items[0] = items[0].model_copy(
            update={
                change: {"id": "replacement", "display_name": "Renamed", "color": "preset9"}[change]
            }
        )
    with pytest.raises(OutlookError, match="missing_or_drifted"):
        verify_ownership(registry, tuple(items))


def test_runtime_identity_cannot_create_or_recolor_categories(tmp_path: Path) -> None:
    cfg = settings(tmp_path)
    transport = CatalogTransport()
    with pytest.raises(OutlookError, match="not_allowed_for_runtime"):
        CategoryCatalog(cfg, transport, identity="writer").create("Unknown")
    assert transport.calls == []
    retired = cfg.model_copy(update={"setup_identity": None})
    with pytest.raises(OutlookError, match="setup_identity_unavailable"):
        CategoryCatalog(retired, transport, identity="setup")


@pytest.mark.parametrize(
    "cursor",
    [
        "https://evil.invalid/x",
        "http://graph.microsoft.com/x",
        "https://graph.microsoft.com/v1.0/users/other/outlook/masterCategories",
        "https://graph.microsoft.com/v1.0/users/x/outlook/masterCategories?$select=body",
    ],
)
def test_category_pagination_never_follows_an_out_of_scope_cursor(
    tmp_path: Path, cursor: str
) -> None:
    transport = CatalogTransport()
    transport.cursor = cursor
    with pytest.raises(OutlookError, match="cursor_out_of_scope"):
        CategoryCatalog(settings(tmp_path), transport, identity="writer").inventory()
    assert len(transport.calls) == 1


def test_duplicate_inventory_identity_is_not_accepted(tmp_path: Path) -> None:
    transport = CatalogTransport()
    transport.rows = [{"id": "same", "displayName": "A", "color": "none"}] * 2
    with pytest.raises(OutlookError, match="inventory_ambiguous"):
        CategoryCatalog(settings(tmp_path), transport, identity="writer").inventory()


def test_owner_scope_and_writer_are_pinned(tmp_path: Path) -> None:
    cfg, registry, transport = provisioned(tmp_path)
    other = cfg.model_copy(
        update={
            "writer_identity": ReaderIdentity(
                client_id=UUID(int=99), certificate_thumbprint="c" * 40
            )
        }
    )
    store = OwnershipStore(other)
    try:
        with pytest.raises(OutlookError, match="scope_or_writer_mismatch"):
            store.load()
    finally:
        store.close()


def test_ownership_save_failure_preserves_prior_committed_registry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg, registry, transport = provisioned(tmp_path)

    def fail(*args):
        raise OSError("synthetic disk failure")

    monkeypatch.setattr("agenttrace_outlook.category_ownership.os.replace", fail)
    store = OwnershipStore(cfg)
    try:
        with pytest.raises(OSError):
            store.save(registry.model_copy(update={"created_at": NOW + timedelta(seconds=1)}))
        assert store.load() == registry
    finally:
        store.close()


@pytest.mark.parametrize(
    "change", ["same_principal", "same_certificate", "control_is_owner", "enable_apply"]
)
def test_invalid_identity_separation_or_silent_activation_is_rejected(
    tmp_path: Path, change: str
) -> None:
    value = settings(tmp_path).model_dump(mode="json")
    if change == "same_principal":
        value["setup_identity"]["client_id"] = value["writer_identity"]["client_id"]
    elif change == "same_certificate":
        value["setup_identity"]["certificate_thumbprint"] = value["writer_identity"][
            "certificate_thumbprint"
        ]
    elif change == "control_is_owner":
        value["control_mailbox_id"] = value["scope"]["mailbox_id"]
    else:
        value["automatic_application_enabled"] = True
    with pytest.raises(ValidationError):
        CategorySettings.model_validate_json(json.dumps(value))


class ProbeTransport:
    def __init__(self):
        self.calls = []
        self.denial = "source_access_denied"
        self.value = {
            "id": "received-one",
            "subject": "AgentTrace synthetic test: scope probe",
            "isDraft": False,
            "categories": ["Personal"],
            "@odata.etag": 'W/"one"',
        }

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if str(UUID(int=9)) in url:
            raise IngestionError(self.denial)
        return json.loads(json.dumps(self.value))


def test_noop_probe_uses_only_unchanged_categories_and_current_etag(tmp_path: Path) -> None:
    cfg = settings(tmp_path)
    transport = ProbeTransport()
    probe = CategoryPermissionProbe(cfg, transport)
    item = probe.metadata("received-one")
    probe.unchanged_patch(item, mailbox_id=cfg.scope.mailbox_id)
    patch = transport.calls[-1]
    assert patch[0] == "PATCH" and patch[2]["body"] == {"categories": ["Personal"]}
    assert patch[2]["headers"]["If-Match"] == 'W/"one"'
    assert all(probe.denied_outside_scope(item).values())


def test_noop_probe_cannot_accept_a_fabricated_or_modified_read_receipt(tmp_path: Path) -> None:
    cfg = settings(tmp_path)
    transport = ProbeTransport()
    probe = CategoryPermissionProbe(cfg, transport)
    with pytest.raises(OutlookError, match="unchanged_read_receipt"):
        probe.unchanged_patch(transport.value, mailbox_id=cfg.scope.mailbox_id)
    item = probe.metadata("received-one")
    item["categories"] = ["AI Agent"]
    with pytest.raises(OutlookError, match="unchanged_read_receipt"):
        probe.unchanged_patch(item, mailbox_id=cfg.scope.mailbox_id)
    assert all(c[0] == "GET" for c in transport.calls)


@pytest.mark.parametrize(
    "code",
    ["source_item_not_found", "source_authentication_expired", "source_temporarily_unavailable"],
)
def test_unavailable_or_missing_is_not_proof_of_scope_denial(tmp_path: Path, code: str) -> None:
    transport = ProbeTransport()
    transport.denial = code
    probe = CategoryPermissionProbe(settings(tmp_path), transport)
    item = probe.metadata("received-one")
    with pytest.raises(IngestionError):
        probe.denied_outside_scope(item)


def decision_for(raw):
    obs = observation(raw)
    assessment = evaluate(obs, raw, None, NOW)
    return obs, Decision(
        scope=SCOPE,
        message_id=obs.message_id,
        source_version=obs.source_version,
        category=assessment.category,
        rule_version=assessment.rule_version,
        basis="production",
        qualification="qualified",
        reason_codes=assessment.reason_codes,
        evidence_refs=("snapshot-sha256:" + sha(raw),),
        decided_at=NOW,
        expires_at=NOW + timedelta(days=30),
    )


def test_current_evidence_preview_preserves_user_categories_without_writing(tmp_path: Path) -> None:
    cfg, registry, transport = provisioned(tmp_path)
    raw = snapshot()
    obs, decision = decision_for(raw)
    message = {
        "id": obs.message_id,
        "subject": "AgentTrace synthetic test: preview",
        "isDraft": False,
        "categories": ["Personal", "Unknown"],
    }
    before = len(transport.calls)
    result = category_preview(
        registry,
        tuple(c.category for c in registry.categories),
        decision,
        obs,
        raw,
        None,
        message,
        NOW,
    )
    assert result["would_change"] and result["unrelated_categories_preserved"]
    assert result["managed_categories_after"] == 1 and not result["mailbox_mutation_performed"]
    assert len(transport.calls) == before


def test_experimental_and_stale_evidence_are_not_previewed_as_eligible(tmp_path: Path) -> None:
    cfg, registry, transport = provisioned(tmp_path)
    raw = snapshot()
    obs, decision = decision_for(raw)
    inventory = tuple(c.category for c in registry.categories)
    message = {
        "id": obs.message_id,
        "subject": "AgentTrace synthetic test: preview",
        "isDraft": False,
        "categories": [],
    }
    with pytest.raises(OutlookError, match="experimental"):
        category_preview(
            registry,
            inventory,
            decision.model_copy(update={"basis": "experimental"}),
            obs,
            raw,
            None,
            message,
            NOW,
        )
    expired = {
        "status": "verified_enrolled_send",
        "observed_version": obs.source_version,
        "expires_at": NOW.timestamp() - 1,
    }
    with pytest.raises(OutlookError, match="evidence_stale"):
        category_preview(registry, inventory, decision, obs, raw, expired, message, NOW)


def test_preview_rejects_definition_replacement_and_wrong_message_targets(tmp_path: Path) -> None:
    cfg, registry, transport = provisioned(tmp_path)
    raw = snapshot()
    obs, decision = decision_for(raw)
    message = {
        "id": "a-different-message",
        "subject": "ordinary customer subject",
        "isDraft": False,
        "categories": [],
    }
    with pytest.raises(OutlookError, match="message_mismatch"):
        category_preview(
            registry,
            tuple(c.category for c in registry.categories),
            decision,
            obs,
            raw,
            None,
            message,
            NOW,
        )


def test_cli_has_no_classification_apply_mode_or_secret_error_output(
    tmp_path: Path, capsys
) -> None:
    from agenttrace_outlook.category_cli import main

    assert (
        main(
            [
                "verify",
                "--settings",
                str(tmp_path / "missing.json"),
                "--output",
                str(tmp_path / "report.json"),
            ]
        )
        == 2
    )
    output = capsys.readouterr().out
    assert str(tmp_path) not in output and "automatic_application_enabled" in output
    with pytest.raises(SystemExit):
        main(["apply", "--settings", "unused", "--output", "unused"])


def test_retired_setup_replay_fails_cleanly_before_loading_credentials(tmp_path: Path) -> None:
    powershell = shutil.which("pwsh")
    if powershell is None:
        pytest.skip("PowerShell guard executes on the designated Windows operator host")
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    source = Path(__file__).resolve().parents[2] / "scripts/configure-category-access.ps1"
    target = scripts / source.name
    target.write_bytes(source.read_bytes())
    private = tmp_path / "work/private/outlook-categories"
    private.mkdir(parents=True)
    proposal = private / "proposal.private.json"
    proposal.write_text("{}", encoding="utf-8")
    (private / "identities.private.json").write_text(
        json.dumps({"category-setup": {"retired_at": NOW.isoformat()}}), encoding="utf-8"
    )
    result = subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-File",
            str(target),
            "-ConfigurationPath",
            str(proposal),
            "-Operation",
            "Configure",
        ],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 2
    assert (result.stdout + result.stderr).strip() == (
        "category_exchange_configuration_failed_see_private_diagnostic"
    )
    assert "retired_setup_requires_new_review" in (
        private / "exchange-error.private.txt"
    ).read_text(encoding="utf-8-sig")
    # There is no Exchange module or credential here: execution must stop before either is used.
    assert not (tmp_path / "work/tools").exists()
