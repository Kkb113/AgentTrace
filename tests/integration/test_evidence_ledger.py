from datetime import timedelta
from uuid import UUID, uuid4

import pytest

from agenttrace_ledger.canonical import LedgerError, text_sha256
from agenttrace_ledger.contracts import ContentInclusion, Generation
from agenttrace_ledger.store import EvidenceLedger, utc_now
from tests.ingestion_support import TENANT, cipher
from tests.ledger_support import BODY, enrolled, observation, principal, send_fact, signed

pytestmark = pytest.mark.integration


@pytest.fixture
def setup_ledger(database):
    ledger = EvidenceLedger(database, cipher(), {TENANT: bytes([9]) * 32})
    message = observation()
    issuer, key, private = enrolled(ledger, message)
    ref = ledger.observe(message)
    return ledger, message, ref, issuer, key, private


def test_exact_send_candidates_restart_and_independent_history(setup_ledger):
    ledger, message, ref, issuer, key, private = setup_ledger
    receipt = signed(message, ref, issuer, key, private, send_fact(message))
    first = ledger.submit(receipt, principal())
    assert first["idempotent_replay"] is False
    assert ledger.submit(receipt, principal())["idempotent_replay"] is True
    view = ledger.view(message.tenant_id, message.mailbox_id, ref, message.version_ref)
    assert view["correlations"]["agent_send_attribution"][0]["classification"] == "exact"
    assert view["correlations"]["content_assessment"] == []
    input_ref = ledger.record_inputs(
        message.tenant_id, message.mailbox_id, ref, message.version_ref
    )
    restarted = EvidenceLedger(ledger.database, cipher(), {TENANT: bytes([9]) * 32})
    assert restarted.view(message.tenant_id, message.mailbox_id, ref, message.version_ref) == view
    history = restarted.history(message.tenant_id, message.mailbox_id, ref)
    assert history[0]["input_ref"] == str(input_ref)
    assert history[0]["view"] == view


def test_altered_replay_is_persisted_as_conflict_without_rewriting_history(setup_ledger):
    ledger, message, ref, issuer, key, private = setup_ledger
    original = signed(message, ref, issuer, key, private, send_fact(message))
    ledger.submit(original, principal())
    ledger.record_inputs(message.tenant_id, message.mailbox_id, ref, message.version_ref)
    altered = signed(
        message,
        ref,
        issuer,
        key,
        private,
        send_fact(message, actor="human"),
        event_id=original.record.event_id,
    )
    with pytest.raises(LedgerError, match="event_reuse_conflict"):
        ledger.submit(altered, principal())
    current = ledger.view(message.tenant_id, message.mailbox_id, ref, message.version_ref)
    assert current["correlations"]["agent_send_attribution"][0]["classification"] == "invalid"
    ledger.record_inputs(message.tenant_id, message.mailbox_id, ref, message.version_ref)
    history = ledger.history(message.tenant_id, message.mailbox_id, ref)
    assert (
        history[0]["view"]["correlations"]["agent_send_attribution"][0]["classification"] == "exact"
    )
    assert history[1]["prior_input_ref"] == history[0]["input_ref"]
    assert history[1]["view"] == current


def test_generation_and_inclusion_are_required_independently_of_send(setup_ledger):
    ledger, message, ref, issuer, key, private = setup_ledger
    gen = signed(
        message,
        ref,
        issuer,
        key,
        private,
        Generation(
            output_sha256=text_sha256(BODY),
            origin="new_generated_output",
            operation="draft_generation",
            provider_ref="synthetic",
        ),
    )
    parent = UUID(ledger.submit(gen, principal())["evidence_ref"])
    gen_only = ledger.view(message.tenant_id, message.mailbox_id, ref, message.version_ref)
    assert gen_only["correlations"]["content_assessment"][0]["classification"] == "context"
    inclusion = signed(
        message,
        ref,
        issuer,
        key,
        private,
        ContentInclusion(
            generation_ref=parent,
            method="authenticated_transfer_lineage",
            region_start=0,
            region_end=len(BODY),
            output_sha256=text_sha256(BODY),
        ),
    )
    ledger.submit(inclusion, principal())
    view = ledger.view(message.tenant_id, message.mailbox_id, ref, message.version_ref)
    assert any(r["classification"] == "exact" for r in view["correlations"]["content_assessment"])
    assert view["correlations"]["agent_send_attribution"] == []


def test_wrong_source_principal_and_revoked_keys_fail_closed(setup_ledger):
    ledger, message, ref, issuer, key, private = setup_ledger
    receipt = signed(message, ref, issuer, key, private, send_fact(message))
    with pytest.raises(LedgerError, match="principal_mismatch"):
        ledger.submit(receipt, principal(subject=str(uuid4())))
    ledger.submit(receipt, principal())
    ledger.revoke(message.tenant_id, message.mailbox_id, issuer, key_ref=key)
    assert (
        ledger.view(message.tenant_id, message.mailbox_id, ref, message.version_ref)[
            "correlations"
        ]["agent_send_attribution"][0]["classification"]
        == "invalid"
    )
    with pytest.raises(LedgerError, match="untrusted"):
        ledger.submit(receipt, principal())


def test_retention_expiry_is_checked_before_raw_evidence_is_opened(setup_ledger, monkeypatch):
    ledger, message, ref, issuer, key, private = setup_ledger
    ledger.submit(signed(message, ref, issuer, key, private, send_fact(message)), principal())
    ledger.record_inputs(message.tenant_id, message.mailbox_id, ref, message.version_ref)
    monkeypatch.setattr("agenttrace_ledger.store.utc_now", lambda: utc_now() + timedelta(days=8))
    with pytest.raises(LedgerError, match="not_found"):
        ledger.view(message.tenant_id, message.mailbox_id, ref, message.version_ref)


@pytest.mark.parametrize(
    "changes",
    [
        {"outcome": "accepted"},
        {"outcome": "failed"},
        {"outcome": "attempted"},
        {"link_method": "candidate", "identifier": None},
        {"actor": "unknown"},
        {"mechanism": "human_interaction_observed"},
    ],
)
def test_accepted_failed_and_candidate_actions_never_become_exact(setup_ledger, changes):
    ledger, message, ref, issuer, key, private = setup_ledger
    ledger.submit(
        signed(message, ref, issuer, key, private, send_fact(message, **changes)), principal()
    )
    assert (
        ledger.view(message.tenant_id, message.mailbox_id, ref, message.version_ref)[
            "correlations"
        ]["agent_send_attribution"][0]["classification"]
        == "candidate"
    )


@pytest.mark.parametrize(
    "role,state", [("recipient", "received"), ("sender", "draft"), ("unknown", "unknown")]
)
def test_recipient_and_draft_observations_cannot_establish_a_send(database, role, state):
    ledger = EvidenceLedger(database, cipher(), {TENANT: bytes([9]) * 32})
    message = observation(copy_role=role, state=state)
    issuer, key, private = enrolled(ledger, message)
    ref = ledger.observe(message)
    ledger.submit(signed(message, ref, issuer, key, private, send_fact(message)), principal())
    assert (
        ledger.view(message.tenant_id, message.mailbox_id, ref, message.version_ref)[
            "correlations"
        ]["agent_send_attribution"][0]["classification"]
        == "candidate"
    )


def test_identical_bodies_subjects_and_duplicate_message_ids_do_not_merge_copies(setup_ledger):
    from agenttrace_ledger.contracts import Identifier

    ledger, message, ref, issuer, key, private = setup_ledger
    other = observation(immutable_id="DifferentSyntheticID", sent_at=message.sent_at)
    other_ref = ledger.observe(other)
    assert other_ref != ref
    weak = send_fact(
        message,
        identifier=Identifier(kind="internet_message_id", value=message.internet_message_id),
    )
    ledger.submit(signed(message, ref, issuer, key, private, weak), principal())
    assert (
        ledger.view(message.tenant_id, message.mailbox_id, ref, message.version_ref)[
            "correlations"
        ]["agent_send_attribution"][0]["classification"]
        == "candidate"
    )
    assert (
        ledger.view(other.tenant_id, other.mailbox_id, other_ref, other.version_ref)[
            "correlations"
        ]["agent_send_attribution"]
        == []
    )
    wrong_id = signed(other, other_ref, issuer, key, private, send_fact(message))
    ledger.submit(wrong_id, principal())
    assert (
        ledger.view(other.tenant_id, other.mailbox_id, other_ref, other.version_ref)[
            "correlations"
        ]["agent_send_attribution"][0]["classification"]
        == "candidate"
    )


@pytest.mark.parametrize(
    "origin,operation,method,output",
    [
        ("echoed_human_input", "draft_generation", "authenticated_transfer_lineage", BODY),
        ("shared_template", "draft_generation", "authenticated_transfer_lineage", BODY),
        ("new_generated_output", "basic_correction", "authenticated_transfer_lineage", BODY),
        ("new_generated_output", "draft_generation", "exact_output_match", BODY),
        ("new_generated_output", "draft_generation", "fuzzy_similarity", BODY),
        (
            "new_generated_output",
            "draft_generation",
            "authenticated_transfer_lineage",
            "Changed text",
        ),
    ],
)
def test_echoes_templates_basic_correction_and_similarity_are_not_verified_origin(
    setup_ledger, origin, operation, method, output
):
    ledger, message, ref, issuer, key, private = setup_ledger
    gen = signed(
        message,
        ref,
        issuer,
        key,
        private,
        Generation(
            output_sha256=text_sha256(output),
            origin=origin,
            operation=operation,
            provider_ref="synthetic",
        ),
    )
    parent = UUID(ledger.submit(gen, principal())["evidence_ref"])
    inc = signed(
        message,
        ref,
        issuer,
        key,
        private,
        ContentInclusion(
            generation_ref=parent,
            method=method,
            region_start=0,
            region_end=len(BODY),
            output_sha256=text_sha256(output),
        ),
    )
    ledger.submit(inc, principal())
    view = ledger.view(message.tenant_id, message.mailbox_id, ref, message.version_ref)
    assert all(r["classification"] != "exact" for r in view["correlations"]["content_assessment"])


def test_generation_reuse_requires_new_scoped_inclusion_and_no_cross_mailbox_lookup(setup_ledger):
    from agenttrace_ledger.contracts import Region

    ledger, message, ref, issuer, key, private = setup_ledger
    parent = UUID(
        ledger.submit(
            signed(
                message,
                ref,
                issuer,
                key,
                private,
                Generation(
                    output_sha256=text_sha256(BODY),
                    origin="new_generated_output",
                    operation="draft_generation",
                    provider_ref="synthetic",
                ),
            ),
            principal(),
        )["evidence_ref"]
    )
    other = observation(
        immutable_id="ReusedTemplateCopy",
        regions=(Region(start=0, end=len(BODY), role="inherited"),),
    )
    other_ref = ledger.observe(other)
    assert (
        ledger.view(other.tenant_id, other.mailbox_id, other_ref, other.version_ref)[
            "correlations"
        ]["content_assessment"]
        == []
    )
    ledger.submit(
        signed(
            other,
            other_ref,
            issuer,
            key,
            private,
            ContentInclusion(
                generation_ref=parent,
                method="authenticated_transfer_lineage",
                region_start=0,
                region_end=len(BODY),
                output_sha256=text_sha256(BODY),
            ),
        ),
        principal(),
    )
    assert (
        ledger.view(other.tenant_id, other.mailbox_id, other_ref, other.version_ref)[
            "correlations"
        ]["content_assessment"][0]["classification"]
        == "candidate"
    )
    foreign = observation(mailbox_id=uuid4(), immutable_id="ForeignMailbox")
    ledger.enroll_scope(foreign.tenant_id, foreign.mailbox_id)
    ledger.enroll_observer(foreign.tenant_id, foreign.mailbox_id, foreign.source_ref)
    foreign_ref = ledger.observe(foreign)
    with pytest.raises(LedgerError, match="untrusted"):
        ledger.submit(
            signed(
                foreign,
                foreign_ref,
                issuer,
                key,
                private,
                ContentInclusion(
                    generation_ref=parent,
                    method="authenticated_transfer_lineage",
                    region_start=0,
                    region_end=len(BODY),
                    output_sha256=text_sha256(BODY),
                ),
            ),
            principal(),
        )


def test_key_rotation_does_not_resurrect_revoked_evidence_and_axes_remain_separate(setup_ledger):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    ledger, message, ref, issuer, key, private = setup_ledger
    old = signed(
        message,
        ref,
        issuer,
        key,
        private,
        Generation(
            output_sha256=text_sha256(BODY),
            origin="new_generated_output",
            operation="draft_generation",
            provider_ref="synthetic",
        ),
    )
    parent = UUID(ledger.submit(old, principal())["evidence_ref"])
    new_key, new_private = uuid4(), Ed25519PrivateKey.generate()
    ledger.enroll_key(
        message.tenant_id,
        message.mailbox_id,
        issuer,
        new_key,
        new_private.public_key().public_bytes_raw(),
        utc_now() - timedelta(days=1),
        utc_now() + timedelta(days=1),
    )
    ledger.submit(
        signed(message, ref, issuer, new_key, new_private, send_fact(message)), principal()
    )
    ledger.submit(
        signed(
            message,
            ref,
            issuer,
            new_key,
            new_private,
            ContentInclusion(
                generation_ref=parent,
                method="authenticated_transfer_lineage",
                region_start=0,
                region_end=len(BODY),
                output_sha256=text_sha256(BODY),
            ),
        ),
        principal(),
    )
    ledger.revoke(message.tenant_id, message.mailbox_id, issuer, key_ref=key)
    replay = signed(
        message, ref, issuer, new_key, new_private, old.record.fact, event_id=old.record.event_id
    )
    assert ledger.submit(replay, principal())["idempotent_replay"] is True
    view = ledger.view(message.tenant_id, message.mailbox_id, ref, message.version_ref)
    assert view["correlations"]["agent_send_attribution"][0]["classification"] == "exact"
    assert not any(
        r["classification"] == "exact" for r in view["correlations"]["content_assessment"]
    )


def test_unchanged_span_edit_lineage_is_separate_from_changed_output_and_old_version(setup_ledger):
    from agenttrace_ledger.contracts import ContentEdit

    ledger, message, ref, issuer, key, private = setup_ledger
    parent = UUID(
        ledger.submit(
            signed(
                message,
                ref,
                issuer,
                key,
                private,
                Generation(
                    output_sha256=text_sha256(BODY),
                    origin="new_generated_output",
                    operation="draft_generation",
                    provider_ref="synthetic",
                ),
            ),
            principal(),
        )["evidence_ref"]
    )
    inclusion = UUID(
        ledger.submit(
            signed(
                message,
                ref,
                issuer,
                key,
                private,
                ContentInclusion(
                    generation_ref=parent,
                    method="authenticated_transfer_lineage",
                    region_start=0,
                    region_end=len(BODY),
                    output_sha256=text_sha256(BODY),
                ),
            ),
            principal(),
        )["evidence_ref"]
    )
    newer = observation(
        source_ref=message.source_ref,
        immutable_id=message.immutable_id,
        observed_at=utc_now(),
        body=BODY,
    )
    assert ledger.observe(newer) == ref
    edit = ContentEdit(
        parent_inclusion_ref=inclusion,
        method="authenticated_unchanged_span",
        before_sha256=text_sha256(BODY),
        after_sha256=text_sha256(BODY),
        region_start=0,
        region_end=len(BODY),
    )
    ledger.submit(
        signed(newer, ref, issuer, key, private, edit, occurred_at=message.observed_at), principal()
    )
    assert (
        ledger.view(newer.tenant_id, newer.mailbox_id, ref, newer.version_ref)["correlations"][
            "content_assessment"
        ][0]["classification"]
        == "exact"
    )
    old_view = ledger.view(message.tenant_id, message.mailbox_id, ref, message.version_ref)
    assert old_view["current_message_version"] is False
    assert not any(
        r["classification"] == "exact" for r in old_view["correlations"]["content_assessment"]
    )


def test_concurrent_replays_and_input_revisions_are_serialized(setup_ledger):
    from concurrent.futures import ThreadPoolExecutor

    ledger, message, ref, issuer, key, private = setup_ledger
    receipt = signed(message, ref, issuer, key, private, send_fact(message))
    with ThreadPoolExecutor(max_workers=4) as pool:
        outcomes = list(pool.map(lambda _: ledger.submit(receipt, principal()), range(4)))
    assert sum(not r["idempotent_replay"] for r in outcomes) == 1
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(
            pool.map(
                lambda _: ledger.record_inputs(
                    message.tenant_id, message.mailbox_id, ref, message.version_ref
                ),
                range(4),
            )
        )
    history = ledger.history(message.tenant_id, message.mailbox_id, ref)
    assert [r["revision"] for r in history] == [1, 2, 3, 4]
    assert all(b["prior_input_ref"] == a["input_ref"] for a, b in zip(history, history[1:]))


def test_separate_anchor_detects_privileged_rollback_and_allows_append(setup_ledger):
    from agenttrace_ledger.retention import checkpoint, verify_checkpoint

    ledger, message, ref, issuer, key, private = setup_ledger
    ledger.record_inputs(message.tenant_id, message.mailbox_id, ref, message.version_ref)
    anchor = checkpoint(ledger, message.tenant_id, message.mailbox_id, ref)
    ledger.record_inputs(message.tenant_id, message.mailbox_id, ref, message.version_ref)
    verify_checkpoint(ledger, anchor, message.tenant_id, message.mailbox_id, ref)
    # Simulate a privileged owner bypass, confined to the fixture's disposable schema.
    with ledger.database.connect() as c:
        c.execute("ALTER TABLE ledger_inputs DISABLE TRIGGER ledger_no_rewrite")
        c.execute("DELETE FROM ledger_inputs WHERE revision=1")
        c.execute("ALTER TABLE ledger_inputs ENABLE TRIGGER ledger_no_rewrite")
    with pytest.raises(LedgerError, match="anchor_integrity"):
        verify_checkpoint(ledger, anchor, message.tenant_id, message.mailbox_id, ref)


@pytest.mark.parametrize(
    "relation,expected",
    [
        ("delivery_copy", "exact_mapping"),
        ("archive_move", "exact_mapping"),
        ("forward_context", "candidate"),
    ],
)
def test_signed_copy_and_archive_mappings_never_propagate_send_or_content(
    setup_ledger, relation, expected
):
    from agenttrace_ledger.contracts import CopyMapping

    ledger, message, ref, issuer, key, private = setup_ledger
    other = observation(
        immutable_id="ArchiveOrRecipientCopy",
        namespace="exchange_store" if relation == "archive_move" else "graph_immutable",
        copy_role="recipient",
        state="received",
    )
    if other.namespace != message.namespace:
        other = other.model_copy(update={"source_ref": uuid4()})
        ledger.enroll_observer(
            other.tenant_id, other.mailbox_id, other.source_ref, namespace=other.namespace
        )
    other_ref = ledger.observe(other)
    fact = CopyMapping(
        other_message_ref=other_ref,
        other_version_ref=other.version_ref,
        relation=relation,
        mapping_basis="authenticated_source_mapping",
    )
    ledger.submit(signed(message, ref, issuer, key, private, fact), principal())
    view = ledger.view(message.tenant_id, message.mailbox_id, ref, message.version_ref)
    assert view["copy_mappings"][0]["classification"] == expected
    assert view["correlations"]["agent_send_attribution"] == []
    assert (
        ledger.view(other.tenant_id, other.mailbox_id, other_ref, other.version_ref)[
            "correlations"
        ]["agent_send_attribution"]
        == []
    )


def test_privileged_message_and_history_metadata_tampering_is_detected(setup_ledger):
    ledger, message, ref, issuer, key, private = setup_ledger
    ledger.record_inputs(message.tenant_id, message.mailbox_id, ref, message.version_ref)
    with ledger.database.connect() as c:
        c.execute("ALTER TABLE ledger_inputs DISABLE TRIGGER ledger_no_rewrite")
        c.execute("UPDATE ledger_inputs SET revision=2")
        c.execute("ALTER TABLE ledger_inputs ENABLE TRIGGER ledger_no_rewrite")
    with pytest.raises(LedgerError, match="metadata_integrity"):
        ledger.history(message.tenant_id, message.mailbox_id, ref)
    with ledger.database.connect() as c:
        c.execute("ALTER TABLE ledger_messages DISABLE TRIGGER ledger_no_rewrite")
        c.execute("UPDATE ledger_messages SET copy_role='recipient'")
        c.execute("ALTER TABLE ledger_messages ENABLE TRIGGER ledger_no_rewrite")
    with pytest.raises(LedgerError, match="metadata_integrity"):
        ledger.view(message.tenant_id, message.mailbox_id, ref, message.version_ref)


def test_issuer_revocation_requires_reassessment_without_rewriting_old_inputs(setup_ledger):
    ledger, message, ref, issuer, key, private = setup_ledger
    ledger.submit(signed(message, ref, issuer, key, private, send_fact(message)), principal())
    ledger.record_inputs(message.tenant_id, message.mailbox_id, ref, message.version_ref)
    ledger.revoke(message.tenant_id, message.mailbox_id, issuer)
    ledger.record_inputs(message.tenant_id, message.mailbox_id, ref, message.version_ref)
    history = ledger.history(message.tenant_id, message.mailbox_id, ref)
    assert (
        history[0]["view"]["correlations"]["agent_send_attribution"][0]["classification"] == "exact"
    )
    assert (
        history[1]["view"]["correlations"]["agent_send_attribution"][0]["classification"]
        == "invalid"
    )


def test_snapshot_reference_is_not_a_claim_that_bytes_or_model_replay_are_available(setup_ledger):
    ledger, message, ref, issuer, key, private = setup_ledger
    new = observation(
        immutable_id="SnapshotExample",
        snapshot_ref=uuid4(),
        snapshot_expires_at=utc_now() + timedelta(days=1),
        snapshot_authorized=True,
    )
    new_ref = ledger.observe(new)
    view = ledger.view(new.tenant_id, new.mailbox_id, new_ref, new.version_ref)
    assert view["replay"]["snapshot_reference_within_retention"] is True
    assert view["replay"]["snapshot_bytes_verified"] is False
    assert view["replay"]["model_reexecution_available"] is False


def test_expired_raw_and_decision_records_are_physically_purged_by_operator_only(setup_ledger):
    from agenttrace_ledger.retention import purge_expired

    ledger, message, ref, issuer, key, private = setup_ledger
    scope = ledger._scope(message.tenant_id, message.mailbox_id)
    with ledger.database.connect() as c:
        c.execute(
            "INSERT INTO ledger_messages(scope_ref,message_ref,version_ref,source_ref,source_event_ref,source_schema_version,namespace,immutable_digest,copy_role,message_state,observed_at,recorded_at,material_cipher,material_digest,expires_at) VALUES(%s,%s,%s,%s,%s,'graph-v1','graph_immutable',%s,'unknown','unknown',now()-interval '8 days',now()-interval '8 days',%s,%s,now()-interval '1 day')",
            (scope, uuid4(), uuid4(), message.source_ref, uuid4(), "0" * 64, b"expired", "0" * 64),
        )
        c.execute(
            "INSERT INTO ledger_inputs(input_ref,scope_ref,message_ref,version_ref,schema_version,rule_version,revision,view_cipher,view_digest,recorded_at,expires_at) VALUES(%s,%s,%s,%s,'1.0','correlation-v1',1,%s,%s,now()-interval '31 days',now()-interval '1 day')",
            (uuid4(), scope, ref, message.version_ref, b"expired", "0" * 64),
        )
    assert ledger.history(message.tenant_id, message.mailbox_id, ref) == []
    result = purge_expired(ledger)
    assert result["ledger_messages"] == 1 and result["ledger_inputs"] == 1
