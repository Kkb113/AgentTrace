"""Authored synthetic study builders. Simulated review identities are not real evidence."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from agenttrace_outlook.accuracy_contracts import (
    AccuracyDataset,
    ActionReview,
    Asset,
    DetectorPacket,
    Enrollment,
    EvaluationCase,
    Frame,
    Groups,
    Reviewer,
    SourceCapture,
    review_binding,
)
from agenttrace_outlook.accuracy_io import detector_digest, digest, policy_digest
from agenttrace_outlook.contracts import Observation, Scope
from agenttrace_outlook.sender_rules import CLAUDE_APP, sha

NOW = datetime.now(UTC).replace(microsecond=0)
SCOPE = Scope(tenant_id=UUID(int=1), mailbox_id=UUID(int=2))
MAILBOX = "owner@example.invalid"


def enrollment() -> Enrollment:
    return Enrollment(
        scope=SCOPE,
        mailbox_address=MAILBOX,
        exchange_mailbox_guid=str(UUID(int=6)),
        publisher_id="fictional",
        publisher_owner_tenant=str(UUID(int=8)),
    )


def packet(
    sent: datetime, *, agent: bool = False, reference: str = "received_one"
) -> DetectorPacket:
    snapshot = {
        "isDraft": False,
        "internetMessageId": "<fictional@example.invalid>",
        "sentDateTime": sent.isoformat(),
        "receivedDateTime": sent.isoformat(),
        "internetMessageHeaders": [
            {"name": "from", "value": MAILBOX},
            {"name": "message-id", "value": "<fictional@example.invalid>"},
            {"name": "date", "value": "Fri, 30 Oct 2026 12:00:00 +0000"},
            {"name": "received", "value": "by mail.example.invalid with ESMTP"},
        ],
    }
    if agent:
        snapshot["internetMessageHeaders"].append(
            {"name": "x-ai-generated", "value": "mcp-office365"}
        )
    observation = Observation(
        scope=SCOPE,
        message_id=reference,
        source_version="version_one",
        observed_at=sent,
        received_at=sent,
        inspection_complete=True,
        source_digest=sha(snapshot),
    )
    frames = []
    for hours in (2, 24):
        at = sent + timedelta(hours=hours, seconds=-10)
        source = None
        if agent:
            row = {
                "id": "event_one",
                "organizationId": str(SCOPE.tenant_id),
                "userPrincipalName": MAILBOX,
                "operation": "Send",
                "createdDateTime": sent.isoformat(),
                "auditData": {
                    "Id": "event_one",
                    "CreationTime": sent.isoformat(),
                    "OrganizationId": str(SCOPE.tenant_id),
                    "TokenTenantId": str(SCOPE.tenant_id),
                    "MailboxOwnerUPN": MAILBOX,
                    "MailboxGuid": str(UUID(int=6)),
                    "Operation": "Send",
                    "Workload": "Exchange",
                    "ResultStatus": "Succeeded",
                    "ClientAppId": CLAUDE_APP,
                    "AppAccessContext": {"ClientAppId": CLAUDE_APP},
                    "ClientRequestId": "request_one",
                    "Item": {
                        "Id": "audit_item",
                        "InternetMessageId": snapshot["internetMessageId"],
                    },
                },
            }
            copies = tuple(
                {
                    "id": name,
                    "parentFolderId": folder,
                    "isDraft": False,
                    "internetMessageId": snapshot["internetMessageId"],
                    "sentDateTime": sent.isoformat(),
                }
                for name, folder in (("sent_one", "sent_folder"), (reference, "inbox"))
            )
            source = SourceCapture(
                state="complete",
                query_id="query_one",
                captured_at=at,
                expires_at=at + timedelta(minutes=5),
                query={
                    "id": "query_one",
                    "status": "succeeded",
                    "filterStartDateTime": (sent - timedelta(minutes=2)).isoformat(),
                    "filterEndDateTime": (sent + timedelta(minutes=2)).isoformat(),
                    "operationFilters": ["Send"],
                    "recordTypeFilters": ["exchangeItem"],
                    "userPrincipalNameFilters": [MAILBOX],
                },
                records=(row,),
                publisher={
                    "appId": CLAUDE_APP,
                    "accountEnabled": True,
                    "appOwnerOrganizationId": str(UUID(int=8)),
                    "verifiedPublisher": {"verifiedPublisherId": "fictional"},
                },
                copies=copies,
                sent_folder_id="sent_folder",
                pagination_complete=True,
            )
        frames.append(Frame(available_at=at, snapshot=snapshot, source=source))
    return DetectorPacket(observation=observation, frames=tuple(frames))


def write_asset(root: Path, relative: str, data: bytes) -> Asset:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_bytes(data)
    path.chmod(0o600)
    return Asset(
        path=relative,
        sha256=digest(data),
        collected_at=NOW - timedelta(minutes=30),
        expires_at=NOW + timedelta(days=6),
    )


def study(root: Path, *, simulated_independent: bool = False) -> AccuracyDataset:
    cases = []
    enrollments = []
    for index, split in enumerate(("development", "calibration", "evaluation")):
        ref = "sample_" + chr(ord("a") + index)
        sent = NOW - timedelta(days=5 - index)
        agent = index > 0
        item = packet(sent, agent=agent, reference="provider_" + str(index))
        enrolled = enrollment().model_copy(
            update={
                "scope": Scope(tenant_id=SCOPE.tenant_id, mailbox_id=UUID(int=20 + index)),
                "mailbox_address": "owner_" + str(index) + "@example.invalid",
            }
        )
        enrollments.append(enrolled)
        raw = item.model_dump(mode="json")
        raw["observation"]["scope"] = enrolled.scope.model_dump(mode="json")
        for frame in raw["frames"]:
            frame["snapshot"]["internetMessageHeaders"][0]["value"] = enrolled.mailbox_address
            if frame["source"]:
                frame["source"]["query"]["userPrincipalNameFilters"] = [enrolled.mailbox_address]
                for event in frame["source"]["records"]:
                    event["userPrincipalName"] = enrolled.mailbox_address
                    event["auditData"]["MailboxOwnerUPN"] = enrolled.mailbox_address
        raw["observation"]["source_digest"] = sha(raw["frames"][0]["snapshot"])
        item = DetectorPacket.model_validate_json(json.dumps(raw))
        input_asset = write_asset(root, ref + "/input.json", item.model_dump_json().encode())
        eml = (
            "From: owner@example.invalid\r\nTo: other@example.invalid\r\nSubject: Review note\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n"
            + [
                "The amber vehicle stopped beside the western entrance before noon.",
                "Review purple documents after afternoon lunch for meeting preparation.",
                "Invented blue shipment arrives next month alongside extra cardboard.",
            ][index]
        ).encode()
        message = write_asset(root, ref + "/message.eml", eml)
        actor = "ai_agent" if agent else "human"
        action = write_asset(
            root,
            ref + "/action.json",
            json.dumps(
                {
                    "actor": actor,
                    "completed_send": True,
                    "message_sha256": message.sha256,
                    "basis": "fictional_test_action",
                }
            ).encode(),
        )
        rights = write_asset(
            root,
            ref + "/rights.txt",
            b"Invented test data; use permitted for software contract tests only.",
        )
        placeholder = Asset(
            path=ref + "/review.json",
            sha256="0" * 64,
            collected_at=NOW - timedelta(minutes=30),
            expires_at=NOW + timedelta(days=6),
        )
        review = ActionReview(
            reviewer_ref="fictional_curator",
            actor=actor,
            reviewed_at=NOW - timedelta(minutes=10),
            blind_to_predictions=True,
            action_source_verified=True,
            capture_custody_verified=True,
            input_sha256=input_asset.sha256,
            action_sha256=action.sha256,
            rights_sha256=rights.sha256,
            case_sha256="0" * 64,
            attestation=placeholder,
        )
        attestation = write_asset(
            root,
            placeholder.path,
            json.dumps(review.model_dump(mode="json", exclude={"attestation"})).encode(),
        )
        review = review.model_copy(update={"attestation": attestation})
        cases.append(
            EvaluationCase(
                case_ref=ref,
                basis="independent_action_history"
                if simulated_independent
                else "authored_adversarial",
                split=split,
                actor=actor,
                approval="approved" if agent else "none",
                creator_ref="fictional_creator",
                prepared_at=sent,
                time_basis="send_record",
                route="outlook_to_outlook",
                source_family="claude_m365_mcp" if agent else "normal_client",
                population="enrolled_claude_poc",
                supported_agent_path=agent,
                families=("approved_agent",) if agent else ("manual_client",),
                groups=Groups(
                    **{
                        key: ref + "_" + key
                        for key in (
                            "sender",
                            "workflow",
                            "thread",
                            "template",
                            "source",
                            "independence_cluster",
                        )
                    }
                ),
                input=input_asset,
                action=action,
                rights=rights,
                message=message,
                reviews=(review,),
            )
        )
    bound = []
    for case in cases:
        review = case.reviews[0].model_copy(update={"case_sha256": review_binding(case)})
        attestation = write_asset(
            root,
            review.attestation.path,
            json.dumps(review.model_dump(mode="json", exclude={"attestation"})).encode(),
        )
        review = review.model_copy(update={"attestation": attestation})
        bound.append(case.model_copy(update={"reviews": (review,)}))
    return AccuracyDataset(
        study_ref="fictional_control_drill",
        synthetic_only=True,
        detector_sha256=detector_digest(),
        policy_sha256=policy_digest(),
        enabled_populations=("enrolled_claude_poc",),
        declared_blind_spots=("external_gmail_agents",),
        enrollments=tuple(enrollments),
        reviewers=(
            Reviewer(
                reviewer_ref="fictional_curator",
                kind="human" if simulated_independent else "fictional_test_identity",
                independent_of_detector=True,
            ),
        ),
        cases=tuple(bound),
    )
