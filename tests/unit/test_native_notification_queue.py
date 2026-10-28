import base64
from io import BytesIO

import pytest

from agenttrace_foundation.database import StorageUnavailable
from agenttrace_ingestion.notifications import NotificationValidator
from agenttrace_ingestion.queue_transport import AzureNotificationQueue
from tests.ingestion_support import cipher, enrollment, notification


class Inbox:
    def __init__(self, events, fail=False):
        self.events, self.fail = events, fail

    def accept(self, items):
        self.events.append("persist")
        if self.fail:
            raise StorageUnavailable("synthetic_failure")


@pytest.mark.parametrize("fail", [False, True])
def test_native_queue_is_deleted_only_after_durable_commit(fail):
    config = enrollment()
    events = []
    payload = base64.b64encode(notification(config, cloud=True)).decode()

    def open_request(request, timeout):
        if request.method == "GET":
            events.append("receive")
            return BytesIO(
                (
                    "<QueueMessagesList><QueueMessage><MessageId>native-id</MessageId><PopReceipt>receipt</PopReceipt><MessageText>"
                    + payload
                    + "</MessageText></QueueMessage></QueueMessagesList>"
                ).encode()
            )
        events.append("delete")
        return BytesIO(b"")

    queue = AzureNotificationQueue(
        "syntheticstorage", lambda **_: "synthetic-token", opener=open_request
    )
    validator = NotificationValidator(config, cipher(), {"synthetic-subscription"})
    if fail:
        with pytest.raises(StorageUnavailable):
            queue.receive_one(Inbox(events, True), validator)
        assert events == ["receive", "persist"]
    else:
        assert queue.receive_one(Inbox(events), validator)
        assert events == ["receive", "persist", "delete"]
