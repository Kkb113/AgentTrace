import json
import re
from datetime import timedelta
from io import BytesIO
from urllib.error import HTTPError
from urllib.parse import unquote, urlsplit
from uuid import UUID, uuid4

from cryptography.hazmat.primitives.asymmetric import rsa

from agenttrace_ingestion.contracts import Enrollment, utc_now
from agenttrace_ingestion.mailbox import MailboxClient
from agenttrace_ingestion.protection import EvidenceCipher
from agenttrace_ingestion.transport import MicrosoftTransport

TENANT = UUID("00000000-0000-4000-8000-000000000001")
MAILBOX = UUID("00000000-0000-4000-8000-000000000002")
CLIENT = UUID("00000000-0000-4000-8000-000000000003")
BODY = (
    "The internal team completed a careful review of the proposed demonstration materials. "
    "Please confirm the test schedule and record any remaining questions before the meeting. "
    "The project owner will review the evidence and prepare a progress update for the participants. "
    "All information in this example is invented and contains no customer records. "
) * 3


def enrollment(**changes):
    return Enrollment(
        source_ref=uuid4(),
        tenant_id=TENANT,
        mailbox_id=MAILBOX,
        collector_client_id=CLIENT,
        folder_ids=("pilot-folder", "pilot-child"),
        client_state="synthetic-validation-secret-for-local-tests",
        **changes,
    )


def cipher():
    return EvidenceCipher(bytes(range(32)))


def keypair():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def notification(
    config, *, message="MessageCaseSensitive", event="event-one", change="created", cloud=False
):
    item = {
        "subscriptionId": "synthetic-subscription",
        "tenantId": str(config.tenant_id),
        "clientState": config.client_state.get_secret_value(),
        "changeType": change,
        "resource": f"Users/{config.mailbox_id}/Messages/{message}",
        "resourceData": {"id": message, "@odata.type": "#Microsoft.Graph.Message"},
    }
    if change in {"missed", "reauthorizationRequired", "subscriptionRemoved"}:
        item["lifecycleEvent"] = item.pop("changeType")
    return json.dumps(
        {
            "id": event,
            "source": f"/tenants/{config.tenant_id}/applications/{config.collector_client_id}",
            "type": "Microsoft.Graph.MessageCreated",
            "specversion": "1.0",
            "time": utc_now().isoformat(),
            "data": item,
        }
        if cloud
        else {"value": [item]}
    ).encode()


class Response(BytesIO):
    def __init__(self, value):
        super().__init__(json.dumps(value).encode())


class GraphSource:
    def __init__(self, config):
        self.config = config
        self.messages = {}
        self.calls = []
        self.delta_pages = []
        self.error = None
        self.cursor = "initial"

    def put(
        self,
        message="MessageCaseSensitive",
        *,
        version="version-one",
        body=BODY,
        folder="pilot-folder",
        modified=None,
        subject="AgentTrace synthetic test: invented",
        internet_id="<invented@example.invalid>",
    ):
        self.messages[message] = {
            "id": message,
            "changeKey": version,
            "parentFolderId": folder,
            "lastModifiedDateTime": (modified or utc_now()).isoformat(),
            "internetMessageId": internet_id,
            "subject": subject,
            "isDraft": False,
            "sentDateTime": utc_now().isoformat(),
            "hasAttachments": False,
            "body": {"content": body, "contentType": "text"},
        }
        return self.messages[message]

    def open(self, request, timeout):
        self.calls.append((request.method, request.full_url, dict(request.headers), request.data))
        if self.error:
            code = self.error
            self.error = None
            raise HTTPError(request.full_url, code, "synthetic", {"Retry-After": "3"}, None)
        path = unquote(urlsplit(request.full_url).path)
        path = re.sub(r"/(users|mailFolders)\('([^']+)'\)", r"/\1/\2", path)
        if path.endswith("/messages/delta"):
            if self.delta_pages:
                return Response(self.delta_pages.pop(0))
            folder = path.split("/mailFolders/")[1].split("/")[0]
            return Response(
                {
                    "value": [
                        {k: v for k, v in m.items() if k != "body"}
                        for m in self.messages.values()
                        if m["parentFolderId"] == folder
                    ],
                    "@odata.deltaLink": self.delta_url(folder),
                }
            )
        if "/messages/" in path:
            message = path.split("/messages/")[1]
            if message not in self.messages:
                raise HTTPError(request.full_url, 404, "synthetic", {}, None)
            return Response(self.messages[message])
        if "/subscriptions" in path:
            return Response(
                {
                    "id": "synthetic-subscription",
                    "expirationDateTime": (utc_now() + timedelta(days=2)).isoformat(),
                }
            )
        raise AssertionError("Unexpected source operation")

    def delta_url(self, folder="pilot-folder", token="opaque%2Btoken%2Fsame%3D"):
        return f"https://graph.microsoft.com/v1.0/users/{self.config.mailbox_id}/mailFolders/{folder}/messages/delta?$deltatoken={token}"

    def client(self):
        return MailboxClient(
            self.config, MicrosoftTransport(lambda **_: "synthetic-runtime-token", opener=self.open)
        )
