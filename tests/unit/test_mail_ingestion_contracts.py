import json
from datetime import timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from agenttrace_ingestion.contracts import IngestionError, utc_now
from agenttrace_ingestion.mailbox import SubscriptionClient
from agenttrace_ingestion.notifications import NotificationValidator
from agenttrace_ingestion.protection import open_content, seal_content
from agenttrace_ingestion.snapshots import SnapshotStore
from agenttrace_ingestion.transport import MicrosoftTransport, retry_after
from tests.ingestion_support import GraphSource, cipher, enrollment, keypair, notification


@pytest.mark.parametrize("cloud", [False, True])
def test_validation_retains_metadata_without_secret_and_preserves_case(cloud):
    config = enrollment()
    validator = NotificationValidator(config, cipher(), {"synthetic-subscription"})
    event = validator.parse(notification(config, cloud=cloud), cloud_events=cloud)[0]
    assert event.message_id == "MessageCaseSensitive"
    assert config.client_state.get_secret_value() not in event.model_dump_json()
    assert "body" not in event.model_dump_json()


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("tenantId", "unknown", "notification_tenant_invalid"),
        ("clientState", "unknown", "notification_client_state_invalid"),
        ("subscriptionId", "unknown", "notification_subscription_invalid"),
        ("resource", "Users/unknown/Messages/item", "notification_mailbox_invalid"),
        ("resourceData", {"body": "private"}, "rich_notifications_not_supported"),
        ("changeType", "send", "notification_change_invalid"),
    ],
)
def test_untrusted_notifications_fail_closed(field, value, reason):
    config = enrollment()
    raw = json.loads(notification(config))
    raw["value"][0][field] = value
    with pytest.raises(IngestionError, match=reason):
        NotificationValidator(config, cipher(), {"synthetic-subscription"}).parse(
            json.dumps(raw).encode()
        )


@pytest.mark.parametrize("raw", [b"", b"[]", b"null", b"{", b'{"value":[]}', b"x" * 65537])
def test_malformed_notification_shapes_are_bounded(raw):
    with pytest.raises(IngestionError):
        NotificationValidator(enrollment(), cipher(), set()).parse(raw)


def test_weak_client_state_is_rejected():
    config = enrollment().model_dump()
    config["client_state"] = "short"
    with pytest.raises(ValidationError):
        type(enrollment()).model_validate(config)


def test_actual_outlook_event_grid_pascal_case_envelope_and_alias_conflicts():
    config = enrollment()
    raw = json.loads(notification(config, cloud=True))
    for canonical, upstream in {
        "subscriptionId": "SubscriptionId",
        "changeType": "ChangeType",
        "resource": "Resource",
        "resourceData": "ResourceData",
    }.items():
        raw["data"][upstream] = raw["data"].pop(canonical)
    raw["data"]["ResourceData"]["Id"] = raw["data"]["ResourceData"].pop("id")
    validator = NotificationValidator(config, cipher(), {"synthetic-subscription"})
    assert (
        validator.parse(json.dumps(raw).encode(), cloud_events=True)[0].message_id
        == "MessageCaseSensitive"
    )
    raw["data"]["subscriptionId"] = "conflicting-subscription"
    with pytest.raises(IngestionError, match="alias_conflict"):
        validator.parse(json.dumps(raw).encode(), cloud_events=True)


@pytest.mark.parametrize(
    "status,reason,retryable",
    [
        (403, "source_access_denied", False),
        (410, "source_cursor_expired", False),
        (429, "source_throttled", True),
        (503, "source_temporarily_unavailable", True),
    ],
)
def test_source_failure_codes_do_not_include_source_response(status, reason, retryable):
    source = GraphSource(enrollment())
    source.error = status
    with pytest.raises(IngestionError) as caught:
        source.client().delta("pilot-folder")
    assert str(caught.value) == reason and caught.value.retryable == retryable
    if retryable:
        assert caught.value.retry_after == 3


def test_token_expiry_refreshes_once_and_reads_use_immutable_ids():
    config = enrollment()
    calls = []
    source = GraphSource(config)
    source.error = 401
    transport = MicrosoftTransport(
        lambda **kwargs: calls.append(kwargs["force_refresh"]) or "synthetic", opener=source.open
    )
    from agenttrace_ingestion.mailbox import MailboxClient

    MailboxClient(config, transport).delta("pilot-folder")
    assert calls == [False, True]
    assert all('IdType="ImmutableId"' == entry[2]["Prefer"] for entry in source.calls)


def test_cursor_origin_mailbox_and_folder_fences_and_verbatim_reuse():
    source = GraphSource(enrollment())
    client = source.client()
    cursor = source.delta_url()
    client.delta("pilot-folder", cursor)
    assert source.calls[-1][1] == cursor
    odata_cursor = cursor.replace("/mailFolders/pilot-folder", "/mailFolders('pilot-folder')")
    client.delta("pilot-folder", odata_cursor)
    assert source.calls[-1][1] == odata_cursor
    for invalid in [
        cursor.replace("graph.microsoft.com", "example.invalid"),
        cursor.replace("pilot-folder", "not-enrolled"),
        cursor + "#fragment",
        cursor.replace("https:", "http:"),
    ]:
        with pytest.raises(IngestionError):
            client.delta("pilot-folder", invalid)


def test_message_body_only_read_after_scope_and_synthetic_subject_checks():
    source = GraphSource(enrollment())
    source.put(subject="ordinary personal message")
    with pytest.raises(IngestionError, match="outside_synthetic"):
        source.client().read("MessageCaseSensitive")
    assert len(source.calls) == 1
    source.put(folder="outside")
    with pytest.raises(IngestionError, match="moved_out"):
        source.client().read("MessageCaseSensitive")
    assert len(source.calls) == 2


def test_subscription_requests_only_maintenance_and_never_rich_body():
    source = GraphSource(enrollment())
    client = SubscriptionClient(source.client())
    client.create("pilot-folder", "https://example.invalid/v1/notifications")
    client.renew("synthetic-subscription")
    client.renew("synthetic-subscription", reauthorize=True)
    body = json.loads(source.calls[0][3])
    assert body["includeResourceData"] is False
    assert body["clientState"] == source.config.client_state.get_secret_value()
    assert all("/subscriptions" in call[1] for call in source.calls)


def test_encryption_context_tamper_and_content_key_version_expiry_boundaries():
    protection = cipher()
    sealed = protection.seal({"body": "private canary"}, context="source-one")
    assert b"private canary" not in sealed
    for value, context in [(sealed, "source-two"), (sealed[:-1] + b"x", "source-one")]:
        with pytest.raises(IngestionError):
            protection.open(value, context=context)
    key = keypair()
    ref = uuid4()
    expiry = utc_now() + timedelta(minutes=15)
    value = seal_content(
        {"authored_text": "private canary"}, key.public_key(), version_ref=ref, expires_at=expiry
    )
    assert (
        open_content(value, key, version_ref=ref, expires_at=expiry, now=utc_now())["authored_text"]
        == "private canary"
    )
    for wrong_key, wrong_ref, now in [
        (keypair(), ref, utc_now()),
        (key, uuid4(), utc_now()),
        (key, ref, expiry),
    ]:
        with pytest.raises(IngestionError):
            open_content(value, wrong_key, version_ref=wrong_ref, expires_at=expiry, now=now)


def test_snapshot_opt_in_encryption_and_expiry(tmp_path):
    config = enrollment()
    with pytest.raises(IngestionError, match="not_authorized"):
        SnapshotStore(tmp_path, cipher(), config).save(
            uuid4(), subject="AgentTrace synthetic test: invented", body="private canary"
        )
    allowed = config.model_copy(update={"raw_snapshots_allowed": True})
    store = SnapshotStore(tmp_path, cipher(), allowed)
    ref = uuid4()
    store.save(ref, subject="AgentTrace synthetic test: invented", body="private canary")
    assert store.read(ref) == "private canary"
    path = tmp_path / (str(ref) + ".enc")
    assert b"private canary" not in path.read_bytes()
    path.write_bytes(
        cipher().seal(
            {
                "body": "private canary",
                "expires_at": (utc_now() - timedelta(seconds=1)).isoformat(),
            },
            context="snapshot:" + str(ref),
        )
    )
    with pytest.raises(IngestionError, match="expired"):
        store.read(ref)
    assert store.purge() == 1 and not path.exists()


@pytest.mark.parametrize(
    "value,expected", [(None, 1), ("10", 10), ("999999", 3600), ("invalid", 1), ("-3", 1)]
)
def test_retry_after_bounds(value, expected):
    assert retry_after(value) == expected
