"""Optional encrypted synthetic replay inputs, inaccessible after seven days."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from uuid import UUID

from .contracts import Enrollment, IngestionError, utc_now
from .mailbox import instant
from .protection import EvidenceCipher


class SnapshotStore:
    def __init__(self, directory: Path, cipher: EvidenceCipher, enrollment: Enrollment):
        self.directory, self.cipher, self.enrollment = directory, cipher, enrollment

    def save(self, version_ref: UUID, *, subject: str, body: str) -> None:
        if not self.enrollment.raw_snapshots_allowed or not subject.startswith(
            self.enrollment.synthetic_subject_prefix
        ):
            raise IngestionError("raw_snapshot_not_authorized")
        self.directory.mkdir(parents=True, exist_ok=True)
        value = self.cipher.seal(
            {"body": body, "expires_at": (utc_now() + timedelta(days=7)).isoformat()},
            context="snapshot:" + str(version_ref),
        )
        path = self.directory / (str(version_ref) + ".enc")
        with path.open("xb") as output:
            output.write(value)

    def read(self, version_ref: UUID) -> str:
        if not self.enrollment.raw_snapshots_allowed:
            raise IngestionError("raw_snapshot_not_authorized")
        value = self.cipher.open(
            (self.directory / (str(version_ref) + ".enc")).read_bytes(),
            context="snapshot:" + str(version_ref),
        )
        if instant(value["expires_at"]) <= utc_now():
            raise IngestionError("raw_snapshot_expired")
        return str(value["body"])

    def purge(self) -> int:
        root = self.directory.resolve()
        count = 0
        for path in root.glob("*.enc"):
            if path.is_symlink() or path.resolve().parent != root:
                raise IngestionError("snapshot_cleanup_path_out_of_scope")
            try:
                ref = UUID(path.stem)
                value = self.cipher.open(path.read_bytes(), context="snapshot:" + str(ref))
                expired = instant(value["expires_at"]) <= utc_now()
            except Exception:
                # Invalid files are quarantined for operator review, never silently removed.
                continue
            if expired:
                path.unlink()
                count += 1
        return count
