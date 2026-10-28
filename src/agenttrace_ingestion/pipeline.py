"""Recover current mailbox state; final actor and authorship decisions are later stages."""

from __future__ import annotations

from agenttrace_text_normalization import BodyExtractor
from cryptography.hazmat.primitives.asymmetric import rsa

from .contracts import IngestionError, SourceNotification, utc_now
from .mailbox import MailboxClient, SubscriptionClient, instant
from .store import IngestionStore


class MailboxPipeline:
    def __init__(
        self,
        store: IngestionStore,
        mailbox: MailboxClient,
        public_key: rsa.RSAPublicKey,
        extractor: BodyExtractor | None = None,
    ):
        self.store, self.mailbox, self.public_key = store, mailbox, public_key
        self.extractor = extractor or BodyExtractor()

    def reconcile(self, folder: str) -> int:
        source = self.mailbox.enrollment.source_ref
        partition = self.store.cipher.reference(str(source), "folder:" + folder)
        lease = self.store.claim_checkpoint(source, partition)
        if lease is None:
            return 0
        try:
            page = self.mailbox.delta(folder, lease.cursor)
            now = utc_now()
            notifications = []
            for item in page["value"]:
                if not isinstance(item, dict) or not isinstance(item.get("id"), str):
                    raise IngestionError("delta_item_invalid")
                # Metadata from ordinary messages is not body-read or persisted.
                # A removed item may lack its old subject; its encrypted locator can
                # invalidate a previously observed copy without assuming deletion.
                if "@removed" not in item and not str(item.get("subject", "")).startswith(
                    self.mailbox.enrollment.synthetic_subject_prefix
                ):
                    continue
                notifications.append(
                    SourceNotification(
                        source_ref=source,
                        event_ref=self.store.cipher.reference(
                            str(source),
                            "delta:"
                            + folder
                            + ":"
                            + item["id"]
                            + ":"
                            + str(item.get("changeKey", item.get("@removed")))
                            + ":"
                            + str(lease.generation),
                        ),
                        subscription_ref="delta-reconciliation",
                        message_id=item["id"],
                        folder_id=folder,
                        change="deleted" if "@removed" in item else "updated",
                        event_time=instant(item["lastModifiedDateTime"])
                        if item.get("lastModifiedDateTime")
                        else None,
                        received_at=now,
                    )
                )
            final = "@odata.deltaLink" in page
            return self.store.commit_page(
                lease,
                notifications,
                page.get("@odata.deltaLink") or page["@odata.nextLink"],
                final=final,
            )
        except IngestionError as error:
            self.store.fail_checkpoint(
                lease, error, reset=error.code in {"source_cursor_expired", "source_cursor_invalid"}
            )
            raise

    def process_one(self) -> bool:
        lease = self.store.claim(self.mailbox.enrollment.source_ref)
        if lease is None:
            return False
        try:
            if lease.notification.change in {
                "missed",
                "subscriptionRemoved",
                "reauthorizationRequired",
            }:
                self.store.complete_lifecycle(lease)
                return True
            if lease.notification.message_id is None:
                raise IngestionError("notification_message_missing")
            snapshot = self.mailbox.read(lease.notification.message_id)
            extraction = (
                self.extractor.extract(
                    snapshot.body, snapshot.body_type, attachments=snapshot.attachment_count
                )
                if snapshot.body is not None
                else self.extractor.unavailable(snapshot.unavailable_reason or "body_unavailable")
            )
            self.store.complete_message(lease, snapshot, extraction, self.public_key)
        except IngestionError as error:
            if error.code in {
                "source_item_not_found",
                "message_moved_out_of_scope",
                "message_outside_synthetic_policy",
            }:
                self.store.unavailable_message(
                    lease,
                    lease.notification.message_id or "",
                    moved=error.code == "message_moved_out_of_scope",
                )
                self.store.gap(
                    lease.source_ref, error.code, started_at=lease.notification.event_time
                )
            else:
                self.store.retry(lease, error)
        return True

    def renew(self, notification_url: str | None = None) -> int:
        client = SubscriptionClient(self.mailbox)
        changed = 0
        active_folders = set()
        for subscription in self.store.subscriptions(self.mailbox.enrollment.source_ref):
            folder = subscription.get("folder_id") or self.mailbox.enrollment.folder_ids[0]
            if (
                subscription["state"] in {"removed", "expired"}
                or subscription["expires_at"] <= utc_now()
            ):
                if subscription["state"] != "expired":
                    self.store.save_subscription(
                        self.mailbox.enrollment.source_ref,
                        subscription["id"],
                        subscription["expires_at"],
                        state="expired",
                    )
                    self.store.gap(
                        self.mailbox.enrollment.source_ref,
                        "subscription_expired_or_removed",
                        started_at=subscription["expires_at"],
                    )
                continue
            if subscription["state"] == "reauthorization_required":
                client.renew(subscription["id"], reauthorize=True)
            if (subscription["expires_at"] - utc_now()).total_seconds() < 43200 or subscription[
                "state"
            ] != "active":
                response = client.renew(subscription["id"])
                self.store.save_subscription(
                    self.mailbox.enrollment.source_ref,
                    subscription["id"],
                    instant(response["expirationDateTime"]),
                )
                changed += 1
            active_folders.add(folder)
        if notification_url:
            for folder in self.mailbox.enrollment.folder_ids:
                if folder not in active_folders:
                    response = client.create(folder, notification_url)
                    self.store.save_subscription(
                        self.mailbox.enrollment.source_ref,
                        response["id"],
                        instant(response["expirationDateTime"]),
                        folder_id=folder,
                    )
                    changed += 1
        return changed
