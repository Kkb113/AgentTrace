"""Bounded background detection collection with independent failure handling."""

from __future__ import annotations

from dataclasses import dataclass, field

from .contracts import IngestionError
from .notifications import NotificationValidator
from .pipeline import MailboxPipeline
from .queue_transport import AzureNotificationQueue


@dataclass
class CycleResult:
    accepted: int = 0
    received: int = 0
    processed: int = 0
    errors: list[str] = field(default_factory=list)


def run_cycle(
    pipeline: MailboxPipeline, queue: AzureNotificationQueue, notification_url: str
) -> CycleResult:
    result = CycleResult()
    try:
        pipeline.renew(notification_url)
    except IngestionError as error:
        result.errors.append(error.code)
        pipeline.store.gap(pipeline.mailbox.enrollment.source_ref, error.code)
    subscriptions = {
        r["id"]
        for r in pipeline.store.subscriptions(pipeline.mailbox.enrollment.source_ref)
        if r["state"] not in {"removed", "expired"}
    }
    validator = NotificationValidator(
        pipeline.mailbox.enrollment, pipeline.store.cipher, subscriptions
    )
    try:
        while result.received < 20 and queue.receive_one(pipeline.store, validator):
            result.received += 1
    except IngestionError as error:
        result.errors.append(error.code)
    # A queue or one folder failure does not suppress the other reconciliation paths.
    for folder in pipeline.mailbox.enrollment.folder_ids:
        try:
            result.accepted += pipeline.reconcile(folder)
        except IngestionError as error:
            result.errors.append(error.code)
    for _ in range(100):
        try:
            if not pipeline.process_one():
                break
            result.processed += 1
        except IngestionError as error:
            result.errors.append(error.code)
    return result
