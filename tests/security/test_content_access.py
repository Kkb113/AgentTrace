from datetime import UTC, datetime, timedelta

import pytest

from agenttrace_foundation.access_policy import (
    EvidenceCapability,
    MailboxReadPolicy,
    require_allowed_egress,
    require_history_access,
)
from agenttrace_foundation.authorization import AccessDenied
from agenttrace_foundation.mail_reader import AuthorizedBody, ReadOnlyMailReader
from agenttrace_foundation.raw_evidence import RawEvidenceReference, read_retained_evidence


def capability(**changes):
    return EvidenceCapability(
        **{
            "mailbox": "approved",
            "message_id": "synthetic-message",
            "version": "version-one",
            "expires_at": datetime.now(UTC) + timedelta(hours=1),
            **changes,
        }
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"mailbox": "excluded"},
        {"message_id": "other"},
        {"synthetic": False},
        {"expires_at": datetime.now(UTC) - timedelta(seconds=1)},
        {"expires_at": datetime.now(UTC) + timedelta(days=8)},
        {"version": ""},
    ],
)
def test_unauthorized_content_never_acquires_a_token_or_calls_graph(changes):
    acquired = []
    reader = ReadOnlyMailReader(
        MailboxReadPolicy("approved", frozenset({"synthetic-message"})),
        lambda: acquired.append(1) or "unused",
    )
    with pytest.raises(AccessDenied):
        reader.read_body(capability(**changes))
    assert not acquired


@pytest.mark.parametrize(
    "url",
    [
        "https://api.openai.com/v1/responses",
        "https://api.anthropic.com/v1/messages",
        "https://graph.microsoft.com/v1.0/me/messages",
        "http://127.0.0.1",
        "file:///private",
    ],
)
def test_content_has_no_outbound_http_and_histories_are_disabled(url):
    with pytest.raises(AccessDenied):
        require_allowed_egress(url, component="content")
    with pytest.raises(AccessDenied, match="connector_disabled"):
        require_history_access()


def test_collector_redirect_credential_and_origin_confusion_are_denied():
    require_allowed_egress("https://graph.microsoft.com/v1.0/users", component="mail_collector")
    for url in [
        "https://graph.microsoft.com.evil.invalid",
        "http://graph.microsoft.com",
        "https://user:password" + chr(64) + "graph.microsoft.com",
        "https://graph.microsoft.com:8443",
        "https://graph.microsoft.com/#fragment",
    ]:
        with pytest.raises(AccessDenied):
            require_allowed_egress(url, component="mail_collector")
    body = AuthorizedBody(capability(), "text", "private synthetic body sentinel")
    assert "private synthetic body sentinel" not in repr(body)


def test_raw_retention_and_scope_are_enforced_before_any_data_plane_read():
    now = datetime.now(UTC)
    requests = []
    for mailbox, captured, expires in [
        ("excluded", now - timedelta(days=1), now + timedelta(days=1)),
        ("approved", now - timedelta(days=8), now - timedelta(seconds=1)),
        ("approved", now - timedelta(days=1), now + timedelta(days=7)),
    ]:
        reference = RawEvidenceReference("fixture", mailbox, captured, expires)
        with pytest.raises(AccessDenied):
            read_retained_evidence(
                reference,
                allowed_mailbox="approved",
                loader=lambda ref: requests.append(ref) or b"unused",
            )
    assert not requests
    current = RawEvidenceReference(
        "fixture", "approved", now - timedelta(hours=1), now + timedelta(hours=1)
    )
    assert (
        read_retained_evidence(
            current, allowed_mailbox="approved", loader=lambda _: b"synthetic"
        ).value
        == b"synthetic"
    )
