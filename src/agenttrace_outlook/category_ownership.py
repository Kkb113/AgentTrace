"""Protected, atomic ownership receipts; names alone never establish service ownership."""

import hashlib
import json
import os
import unicodedata
from datetime import datetime
from pathlib import Path

from agenttrace_feasibility.validation import canonical_bytes, load_json

from .category_catalog import CategoryCatalog
from .category_contracts import (
    PRESETS,
    CategoryOwnership,
    CategorySettings,
    MasterCategory,
    OwnedCategory,
)
from .errors import OutlookError
from .locking import ProcessLock


def normalized_name(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


class OwnershipStore:
    def __init__(self, settings: CategorySettings):
        self.settings = settings
        self.directory = Path(settings.ownership_directory)
        for path in (self.directory, *self.directory.parents):
            if path.is_symlink() or path.is_junction():
                raise OutlookError("category_ownership_path_alias")
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        for name in ("ownership.json", "ownership.pending", "ownership.lock"):
            path = self.directory / name
            if path.is_symlink() or (path.exists() and path.stat().st_nlink != 1):
                raise OutlookError("category_ownership_path_alias")
        self.path = self.directory / "ownership.json"
        self.lock = ProcessLock(self.directory / "ownership.lock")

    def close(self) -> None:
        self.lock.close()

    def load(self) -> CategoryOwnership | None:
        if not self.path.exists():
            return None
        value = CategoryOwnership.model_validate_json(canonical_bytes(load_json(self.path)))
        if (
            value.scope != self.settings.scope
            or value.writer_client_id != self.settings.writer_identity.client_id
        ):
            raise OutlookError("category_ownership_scope_or_writer_mismatch")
        return value

    def save(self, value: CategoryOwnership) -> None:
        if (
            value.scope != self.settings.scope
            or value.writer_client_id != self.settings.writer_identity.client_id
        ):
            raise OutlookError("category_ownership_scope_or_writer_mismatch")
        pending = self.directory / "ownership.pending"
        descriptor = os.open(pending, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
            output.write(value.model_dump_json(indent=2) + "\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(pending, self.path)


def verify_ownership(
    registry: CategoryOwnership,
    inventory: tuple[MasterCategory, ...],
    *,
    require_complete: bool = True,
) -> None:
    if require_complete and len(registry.categories) != 3:
        raise OutlookError("category_ownership_incomplete")
    by_id = {c.id: c for c in inventory}
    if len(by_id) != len(inventory):
        raise OutlookError("category_inventory_ambiguous")
    for owned in registry.categories:
        if by_id.get(owned.category.id) != owned.category:
            raise OutlookError("owned_category_missing_or_drifted")
        if (
            sum(
                normalized_name(c.display_name) == normalized_name(owned.category.display_name)
                for c in inventory
            )
            != 1
        ):
            raise OutlookError("owned_category_name_ambiguous")


def provision(store: OwnershipStore, catalog: CategoryCatalog, now: datetime) -> CategoryOwnership:
    if (
        catalog.identity != "setup"
        or catalog.settings != store.settings
        or store.settings.setup_identity is None
    ):
        raise OutlookError("category_setup_identity_required")
    registry = store.load() or CategoryOwnership(
        scope=store.settings.scope,
        writer_client_id=store.settings.writer_identity.client_id,
        created_at=now,
    )
    inventory = catalog.inventory()
    verify_ownership(registry, inventory, require_complete=False)
    owned_labels = {c.label for c in registry.categories}
    for label in PRESETS:
        matches = [
            c for c in inventory if normalized_name(c.display_name) == normalized_name(label)
        ]
        if label not in owned_labels and matches:
            raise OutlookError("existing_unowned_category_name_conflict")
    # Record successful creates individually. A lost POST response has no receipt:
    # a later name collision blocks recovery instead of silently adopting user data.
    for label in PRESETS:
        if label in owned_labels:
            continue
        category = catalog.create(label)
        receipt = hashlib.sha256(
            json.dumps(category.model_dump(), sort_keys=True).encode()
        ).hexdigest()
        owned = OwnedCategory(
            label=label,
            category=category,
            created_at=now,
            setup_client_id=store.settings.setup_identity.client_id,
            creation_receipt_sha256=receipt,
        )
        registry = registry.model_copy(update={"categories": (*registry.categories, owned)})
        store.save(registry)
    verify_ownership(registry, catalog.inventory())
    return registry
