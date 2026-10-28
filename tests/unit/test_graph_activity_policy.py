import pytest

from agenttrace_ingestion.activity_policy import (
    ActivityScope,
    minimal_request_uri,
    send_request_observed,
)
from agenttrace_ingestion.contracts import IngestionError
from tests.ingestion_support import CLIENT, MAILBOX, TENANT


def test_transform_is_narrow_and_drops_sensitive_fields_before_storage():
    scope = ActivityScope(TENANT, MAILBOX, frozenset({CLIENT}), frozenset({CLIENT}))
    transform = scope.transform()
    assert transform.startswith("source | where AadTenantId")
    assert str(TENANT) in transform and str(MAILBOX) in transform and str(CLIENT) in transform
    assert "split(RequestUri, '?')[0]" in transform
    projection = transform.split(" | project ")[1]
    assert (
        "IPAddress" not in projection
        and "Roles" not in projection
        and "Scopes" not in projection
        and "UserAgent" not in projection
    )


@pytest.mark.parametrize(
    "clients,collectors",
    [
        (frozenset(), frozenset()),
        (frozenset({CLIENT}), frozenset()),
        (frozenset({CLIENT}), frozenset({TENANT})),
    ],
)
def test_unbounded_or_inconsistent_source_scopes_are_rejected(clients, collectors):
    with pytest.raises(ValueError):
        ActivityScope(TENANT, MAILBOX, clients, collectors)


@pytest.mark.parametrize(
    "suffix",
    [
        "sendMail",
        "messages/example/send",
        "messages/example/reply",
        "messages/example/replyAll",
        "messages/example/forward",
    ],
)
@pytest.mark.parametrize("root", ["me", "users/synthetic-user"])
def test_supported_send_api_calls_are_only_send_observations(root, suffix):
    assert send_request_observed("POST", f"https://graph.microsoft.com/v1.0/{root}/{suffix}", 202)


@pytest.mark.parametrize(
    "method,path,status",
    [
        ("GET", "me/sendMail", 200),
        ("POST", "me/sendMail", 403),
        ("POST", "me/messages", 201),
        ("PATCH", "me/messages/example", 200),
        ("POST", "me/messages/example/createReply", 201),
        ("POST", "me/drive/sendMail", 202),
        ("POST", "groups/synthetic/sendMail", 202),
        ("POST", "me/messages/example/move", 201),
    ],
)
def test_drafts_edits_reads_failures_and_other_resources_are_not_send_events(method, path, status):
    assert not send_request_observed(method, "https://graph.microsoft.com/v1.0/" + path, status)


def test_uri_minimization_removes_queries_and_fragments_without_changing_object_path():
    url = "https://graph.microsoft.com/v1.0/me/messages?search=synthetic-sensitive-canary#fragment"
    assert minimal_request_uri(url) == "https://graph.microsoft.com/v1.0/me/messages"


@pytest.mark.parametrize(
    "url",
    [
        "http://graph.microsoft.com/v1.0/me",
        "https://example.invalid/me",
        "https://graph.microsoft.com.evil.invalid/me",
        "https://graph.microsoft.com:443/me",
    ],
)
def test_untrusted_activity_uris_are_rejected(url):
    with pytest.raises(IngestionError):
        minimal_request_uri(url)
