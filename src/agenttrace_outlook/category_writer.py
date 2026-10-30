"""Fenced decision-bound write intents with conservative uncertainty and rollback handling."""

import json
from typing import Any

from agenttrace_foundation.authorization import AccessDenied
from agenttrace_ingestion.contracts import IngestionError

from .category_catalog import CategoryCatalog
from .category_contracts import CategoryOwnership, Label
from .category_endpoint import CategoryEndpoint
from .category_ownership import verify_ownership
from .category_preview import category_preview
from .category_write_contracts import CategoryEndpointQualification
from .contracts import Decision, Observation
from .eligibility import require_annotation_eligible
from .errors import OutlookError
from .mail_semantics import sender_snapshot
from .rule_store import RuleStore
from .sender_rules import evaluate, sha
from .state import StateStore

TERMINAL = {
    "applied",
    "unchanged",
    "reconciled",
    "superseded",
    "blocked",
    "rolled_back",
    "rollback_blocked",
}
UNCERTAIN = {"prepared", "uncertain", "rollback_pending"}


class CategoryWriter:
    def __init__(
        self,
        store: StateStore,
        catalog: CategoryCatalog,
        registry: CategoryOwnership,
        qualification: CategoryEndpointQualification | None,
    ):
        self.store, self.catalog, self.registry, self.qualification = (
            store,
            catalog,
            registry,
            qualification,
        )
        self.endpoint = CategoryEndpoint(catalog.settings, catalog.transport)
        self.rules = RuleStore(store)
        if (
            store.config.scope != registry.scope
            or catalog.settings.scope != registry.scope
            or registry.writer_client_id != catalog.settings.writer_identity.client_id
            or not store.config.sync_enabled
            or catalog.identity != "writer"
            or store.config.reader_identity is None
            or store.config.reader_identity.client_id == registry.writer_client_id
            or (
                store.config.sender_source
                and store.config.sender_source.audit_identity.client_id == registry.writer_client_id
            )
        ):
            raise OutlookError("separate_scoped_category_writer_required")

    def row(self, identity: int) -> dict[str, Any]:
        with self.store.transaction(lease=self.store.lease) as db:
            row = db.execute(
                "SELECT i.*,d.payload AS decision,d.observation_id,d.version AS version,o.payload AS observation,m.current_observation,m.decision_version AS latest_version FROM category_intents i JOIN decisions d ON d.id=i.decision_id JOIN observations o ON o.id=d.observation_id JOIN messages m ON m.message_id=i.message_id WHERE i.id=?",
                (identity,),
            ).fetchone()
        if row is None:
            raise OutlookError("category_intent_not_found")
        return dict(row)

    def _current(self, row: dict[str, Any], message: dict[str, Any] | None = None) -> Decision:
        decision = Decision.model_validate_json(row["decision"])
        observation = Observation.model_validate_json(row["observation"])
        require_annotation_eligible(decision, self.registry.scope, self.store.clock())
        if (
            row["version"] != row["latest_version"]
            or row["observation_id"] != row["current_observation"]
        ):
            raise OutlookError("category_decision_superseded")
        snapshot, source = (
            self.rules.snapshot(observation),
            self.rules.source(row["observation_id"]),
        )
        if snapshot is None:
            raise OutlookError("category_snapshot_unavailable")
        providers = (
            self.store.config.sender_source.agent_providers
            if self.store.config.sender_source
            else ()
        )
        expected = evaluate(observation, snapshot, source, self.store.clock(), providers=providers)
        refs = (
            (*expected.evidence_refs, "snapshot-sha256:" + observation.source_digest)
            if expected.category != "Unknown"
            else expected.evidence_refs
        )
        if (
            decision.category != expected.category
            or decision.rule_version != expected.rule_version
            or decision.reason_codes != expected.reason_codes
            or decision.evidence_refs != refs
        ):
            raise OutlookError("category_decision_evidence_changed")
        if message is not None:
            category_preview(
                self.registry,
                self.catalog_inventory,
                decision,
                observation,
                snapshot,
                source,
                message,
                self.store.clock(),
                providers=providers,
            )
            if sha(sender_snapshot(message)[0]) != observation.source_digest:
                raise OutlookError("category_live_evidence_changed")
            self._location(message)
        return decision

    def _location(self, message: dict[str, Any]) -> None:
        with self.store.transaction(lease=self.store.lease) as db:
            item = db.execute(
                "SELECT status FROM sync_items WHERE message_id=?", (message["id"],)
            ).fetchone()
            folder = db.execute(
                "SELECT excluded,active FROM folders WHERE id=?", (message["parentFolderId"],)
            ).fetchone()
        if not item or item[0] != "eligible" or not folder or folder[0] or not folder[1]:
            raise OutlookError("category_message_not_in_receiving_scope")

    def plan(self, message_id: str | None = None) -> list[int]:
        self.catalog_inventory = self.catalog.inventory()
        verify_ownership(self.registry, self.catalog_inventory)
        with self.store.transaction(lease=self.store.lease) as db:
            rows = db.execute(
                "SELECT d.id,d.message_id,d.payload FROM decisions d JOIN messages m ON m.message_id=d.message_id AND m.decision_version=d.version WHERE (? IS NULL OR d.message_id=?) AND (? IS NOT NULL OR NOT EXISTS(SELECT 1 FROM category_intents i WHERE i.decision_id=d.id)) ORDER BY d.id LIMIT ?",
                (message_id, message_id, message_id, self.store.config.batch_size),
            ).fetchall()
            result = []
            for row in rows:
                require_annotation_eligible(
                    Decision.model_validate_json(row[2]), self.registry.scope, self.store.clock()
                )
                now = self.store.clock().timestamp()
                db.execute(
                    "INSERT OR IGNORE INTO category_intents(decision_id,message_id,status,created,updated) VALUES (?,?,'pending',?,?)",
                    (row[0], row[1], now, now),
                )
                result.append(
                    int(
                        db.execute(
                            "SELECT id FROM category_intents WHERE decision_id=?", (row[0],)
                        ).fetchone()[0]
                    )
                )
        return result

    def _status(
        self, identity: int, status: str, code: str | None = None, *, delay: int = 0
    ) -> None:
        with self.store.transaction(lease=self.store.lease) as db:
            db.execute(
                "UPDATE category_intents SET status=?,error_code=?,due=?,updated=? WHERE id=?",
                (
                    status,
                    code,
                    self.store.clock().timestamp() + delay,
                    self.store.clock().timestamp(),
                    identity,
                ),
            )

    def _attempt(self, identity: int) -> dict[str, Any] | None:
        with self.store.transaction(lease=self.store.lease) as db:
            row = db.execute(
                "SELECT * FROM category_attempts WHERE intent_id=? ORDER BY id DESC LIMIT 1",
                (identity,),
            ).fetchone()
        return dict(row) if row else None

    def _save_attempt(self, attempt_id: int, status: str, payload: dict[str, Any]) -> None:
        with self.store.transaction(lease=self.store.lease) as db:
            db.execute(
                "UPDATE category_attempts SET status=?,payload=? WHERE id=?",
                (status, json.dumps(payload), attempt_id),
            )

    def _gate(self) -> None:
        if self.qualification is None:
            raise OutlookError("category_endpoint_not_qualified")
        self.qualification.require_current(self.catalog.settings, self.store.clock())
        self.catalog_inventory = self.catalog.inventory()
        verify_ownership(self.registry, self.catalog_inventory)

    def _confirmed(
        self, row: dict[str, Any], attempt: dict[str, Any], current: dict[str, Any]
    ) -> bool:
        self._location(current)
        payload = json.loads(attempt["payload"])
        if (
            set(current["categories"]) == set(payload["after_categories"])
            and sha(sender_snapshot(current)[0]) == payload["semantic_hash"]
        ):
            attributed = current["@odata.etag"] == payload.get("response_etag")
            self._save_attempt(attempt["id"], "confirmed" if attributed else "reconciled", payload)
            self._status(
                row["id"],
                "rolled_back"
                if attempt["operation"] == "rollback"
                else "applied"
                if attributed
                else "reconciled",
            )
            return True
        return False

    def _recover(
        self, row: dict[str, Any], attempt: dict[str, Any], current: dict[str, Any]
    ) -> bool:
        if self._confirmed(row, attempt, current):
            return True
        payload = json.loads(attempt["payload"])
        if (
            current["@odata.etag"] != payload["before_etag"]
            or current["categories"] != payload["before_categories"]
        ):
            self._status(
                row["id"],
                "rollback_blocked" if attempt["operation"] == "rollback" else "blocked",
                "category_ambiguous_outcome_with_later_change",
            )
            return True
        return False

    def step(self, identity: int) -> dict[str, Any]:
        self.store.heartbeat()
        row = self.row(identity)
        if row["status"] in TERMINAL or row["due"] > self.store.clock().timestamp():
            return self.summary(identity)
        operation = "rollback" if row["status"] == "rollback_pending" else "apply"
        attempt = self._attempt(identity)
        if row["status"] in {"prepared", "uncertain"} and attempt:
            operation = attempt["operation"]
        try:
            self._gate()
            current = self.endpoint.read(row["message_id"])
            if attempt and attempt["status"] in {"prepared", "uncertain"}:
                if self._recover(row, attempt, current):
                    return self.summary(identity)
            if row["attempts"] >= self.store.config.max_attempts:
                raise OutlookError("category_write_attempt_limit")
            label: Label | None
            if operation == "apply":
                decision = self._current(row, current)
                label = decision.category
                with self.store.transaction(lease=self.store.lease) as db:
                    other = db.execute(
                        "SELECT id FROM category_intents WHERE message_id=? AND id!=? AND status IN ('prepared','uncertain','rollback_pending') LIMIT 1",
                        (row["message_id"], identity),
                    ).fetchone()
                if other:
                    raise OutlookError("category_prior_mutation_unresolved")
            else:
                label = None
                self._rollback_proof(row, current)
            after = self.endpoint.merged(current["categories"], self.registry, label)
            if set(after) == set(current["categories"]):
                self._status(identity, "rolled_back" if operation == "rollback" else "unchanged")
                return self.summary(identity)
            payload = {
                "before_etag": current["@odata.etag"],
                "before_categories": current["categories"],
                "after_categories": after,
                "semantic_hash": sha(sender_snapshot(current)[0]),
                "added_label": label if label and label not in current["categories"] else None,
                "response_etag": None,
            }
            # Commit the exact intent before IO. A crash here is always treated as uncertain.
            with self.store.transaction(lease=self.store.lease) as db:
                cursor = db.execute(
                    "INSERT INTO category_attempts(intent_id,operation,status,payload,created) VALUES (?,?,'prepared',?,?)",
                    (identity, operation, json.dumps(payload), self.store.clock().timestamp()),
                )
                attempt_id = int(cursor.lastrowid or 0)
                db.execute(
                    "UPDATE category_intents SET status='prepared',attempts=attempts+1,error_code=NULL,updated=? WHERE id=?",
                    (self.store.clock().timestamp(), identity),
                )
            self.store.heartbeat()
            try:
                # Recheck freshness after the durable prepare and immediately before sending.
                if self.qualification is None:
                    raise OutlookError("category_endpoint_not_qualified")
                self.qualification.require_current(self.catalog.settings, self.store.clock())
                if operation == "apply":
                    self._current(row, current)
            except OutlookError as error:
                self._save_attempt(attempt_id, "rejected", payload)
                self._status(
                    identity,
                    "rollback_blocked" if operation == "rollback" else "blocked",
                    error.code,
                )
                return self.summary(identity)
            try:
                response = self.endpoint.write(current, self.registry, label)
            except IngestionError as error:
                if error.code == "source_version_changed":
                    self._save_attempt(attempt_id, "conflict", payload)
                    self._status(
                        identity,
                        "rollback_pending" if operation == "rollback" else "pending",
                        error.code,
                        delay=1,
                    )
                elif error.retryable:
                    self._save_attempt(attempt_id, "uncertain", payload)
                    self._status(identity, "uncertain", error.code, delay=error.retry_after or 1)
                else:
                    self._save_attempt(attempt_id, "rejected", payload)
                    self._status(
                        identity,
                        "rollback_blocked" if operation == "rollback" else "blocked",
                        error.code,
                    )
                return self.summary(identity)
            payload["response_etag"] = (
                response.get("@odata.etag") if response.get("id") == current["id"] else None
            )
            self._save_attempt(attempt_id, "uncertain", payload)
            self._status(identity, "uncertain", "category_readback_pending")
            observed = self.endpoint.read(row["message_id"])
            saved = self._attempt(identity)
            if saved is None or not self._confirmed(row, saved, observed):
                self._status(identity, "uncertain", "category_readback_mismatch", delay=1)
        except (IngestionError, OutlookError, AccessDenied) as error:
            code = getattr(error, "code", "category_authentication_unavailable")
            current_row = self.row(identity)
            if current_row["status"] in {"prepared", "uncertain"}:
                self._status(identity, "uncertain", code, delay=2)
            elif (
                getattr(error, "retryable", False)
                and row["attempts"] < self.store.config.max_attempts
            ):
                with self.store.transaction(lease=self.store.lease) as db:
                    db.execute(
                        "UPDATE category_intents SET attempts=attempts+1 WHERE id=?", (identity,)
                    )
                self._status(
                    identity, row["status"], code, delay=getattr(error, "retry_after", None) or 2
                )
            else:
                self._status(
                    identity,
                    "rollback_blocked"
                    if operation == "rollback"
                    else "superseded"
                    if code == "category_decision_superseded"
                    else "blocked",
                    code,
                )
        return self.summary(identity)

    def _rollback_proof(self, row: dict[str, Any], current: dict[str, Any]) -> None:
        self._location(current)
        with self.store.transaction(lease=self.store.lease) as db:
            proof = db.execute(
                "SELECT payload FROM category_attempts WHERE intent_id=? AND operation='apply' AND status='confirmed' ORDER BY id DESC LIMIT 1",
                (row["id"],),
            ).fetchone()
        if not proof:
            raise OutlookError("category_rollback_ownership_unproven")
        payload = json.loads(proof[0])
        label = payload.get("added_label")
        if (
            not label
            or current["@odata.etag"] != payload["response_etag"]
            or set(current["categories"]) != set(payload["after_categories"])
        ):
            raise OutlookError("category_rollback_later_edit_or_unowned_label")
        if sha(sender_snapshot(current)[0]) != payload["semantic_hash"]:
            raise OutlookError("category_rollback_message_changed")

    def request_rollback(self, identity: int) -> None:
        row = self.row(identity)
        if row["status"] == "rolled_back":
            return
        if row["status"] != "applied":
            raise OutlookError("category_rollback_requires_attributed_apply")
        with self.store.transaction(lease=self.store.lease) as db:
            db.execute(
                "UPDATE category_intents SET status='rollback_pending',attempts=0,due=0,error_code=NULL,updated=? WHERE id=?",
                (self.store.clock().timestamp(), identity),
            )

    def request_retry(self, identity: int) -> None:
        row = self.row(identity)
        if row["status"] not in {
            "pending",
            "prepared",
            "uncertain",
            "blocked",
            "rollback_pending",
            "rollback_blocked",
        }:
            raise OutlookError("category_retry_requires_unfinished_intent")
        status = (
            "rollback_pending"
            if row["status"] in {"rollback_pending", "rollback_blocked"}
            else "uncertain"
            if row["status"] in {"prepared", "uncertain"}
            else "pending"
        )
        # Keep all receipts; retry still reconciles IO and rechecks current evidence.
        with self.store.transaction(lease=self.store.lease) as db:
            db.execute(
                "UPDATE category_intents SET status=?,attempts=0,due=0,error_code=NULL,updated=? WHERE id=?",
                (status, self.store.clock().timestamp(), identity),
            )

    def summary(self, identity: int) -> dict[str, Any]:
        row = self.row(identity)
        attempt = self._attempt(identity)
        return {
            "intent_id": identity,
            "message_ref_sha256": sha(row["message_id"]),
            "status": row["status"],
            "attempts": row["attempts"],
            "error_code": row["error_code"],
            "classification_changed": False,
            "write_attributed": bool(
                attempt and attempt["status"] == "confirmed" and attempt["operation"] == "apply"
            ),
            "rollback_attributed": bool(
                attempt and attempt["status"] == "confirmed" and attempt["operation"] == "rollback"
            ),
        }

    def verify(self, identity: int) -> dict[str, Any]:
        self._gate()
        row = self.row(identity)
        current = self.endpoint.read(row["message_id"])
        result = self.summary(identity)
        result["mailbox_category_present"] = (
            Decision.model_validate_json(row["decision"]).category in current["categories"]
        )
        try:
            self._current(row, current)
        except OutlookError:
            result["classification_evidence_current"] = False
        else:
            result["classification_evidence_current"] = True
        result["mailbox_mutation_performed"] = False
        return result
