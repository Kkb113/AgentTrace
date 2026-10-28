"""Run read-only synthetic collection, health, scoped replay and retention maintenance."""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict
from pathlib import Path
from uuid import UUID

from agenttrace_foundation.database import StorageUnavailable

from .contracts import IngestionError
from .daemon import run_cycle
from .mailbox import SubscriptionClient, instant
from .notifications import NotificationValidator
from .queue_transport import AzureNotificationQueue
from .runtime import load


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=[
            "enroll",
            "collect",
            "subscribe",
            "renew",
            "receive",
            "health",
            "replay",
            "purge",
            "watch",
        ],
    )
    parser.add_argument("--configuration", type=Path, required=True)
    parser.add_argument("--event-ref", type=UUID)
    parser.add_argument("--iterations", type=int, default=0)
    args = parser.parse_args()
    try:
        config, enrollment, store, pipeline, provider = load(
            args.configuration, operator=args.command in {"enroll", "purge"}
        )
        result = {"operation": args.command}
        if args.command == "watch":
            queue = AzureNotificationQueue(
                config["notification_storage_account"],
                lambda *, force_refresh=False: provider.token(
                    "https://storage.azure.com", force_refresh=force_refresh
                ),
            )
            count = 0
            while True:
                print(
                    json.dumps(asdict(run_cycle(pipeline, queue, config["notification_url"]))),
                    flush=True,
                )
                count += 1
                if args.iterations > 0 and count >= args.iterations:
                    return 0
                time.sleep(15)
        elif args.command == "enroll":
            store.enroll(enrollment)
        elif args.command == "collect":
            accepted = sum(pipeline.reconcile(folder) for folder in enrollment.folder_ids)
            processed = 0
            while processed < 100 and pipeline.process_one():
                processed += 1
            result.update({"accepted": accepted, "processed": processed})
        elif args.command == "subscribe":
            for folder in enrollment.folder_ids:
                response = SubscriptionClient(pipeline.mailbox).create(
                    folder, config["notification_url"]
                )
                store.save_subscription(
                    enrollment.source_ref,
                    response["id"],
                    instant(response["expirationDateTime"]),
                    folder_id=folder,
                )
        elif args.command == "renew":
            result["renewed"] = pipeline.renew(config.get("notification_url"))
        elif args.command == "receive":
            subscriptions = {
                r["id"]
                for r in store.subscriptions(enrollment.source_ref)
                if r["state"] not in {"removed", "expired"}
            }
            validator = NotificationValidator(enrollment, store.cipher, subscriptions)
            queue = AzureNotificationQueue(
                config["notification_storage_account"],
                lambda *, force_refresh=False: provider.token(
                    "https://storage.azure.com", force_refresh=force_refresh
                ),
            )
            received = 0
            while received < 20 and queue.receive_one(store, validator):
                received += 1
            result["received"] = received
        elif args.command == "health":
            result["health"] = store.health(enrollment.source_ref)
        elif args.command == "replay":
            if args.event_ref is None:
                raise IngestionError("exact_event_reference_required")
            result["replayed"] = store.replay(enrollment.source_ref, args.event_ref)
        elif args.command == "purge":
            result["purged"] = store.purge()
        print(json.dumps(result, sort_keys=True))
        return 0
    except (IngestionError, StorageUnavailable) as error:
        print(
            json.dumps(
                {"operation": args.command, "status": "unavailable", "reason_code": str(error)}
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
