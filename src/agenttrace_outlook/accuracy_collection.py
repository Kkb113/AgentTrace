"""Prepare empty curator instructions/templates; never fabricate labels or send messages."""

from pathlib import Path

from .accuracy_contracts import AccuracyDataset, DetectorPacket
from .accuracy_io import detector_digest, policy_digest, write_new

GUIDE = """# Independent sender-study collection

This is an empty collection pack, not a completed independent dataset.
AgentTrace never sends test emails. Authorized operators prepare synthetic sends
using their normal clients or existing agents outside AgentTrace.

Start with a small pilot across manual Outlook/Gmail sending, copied AI wording
sent manually, agent draft/manual Send, approved and autonomous Claude sends,
ordinary scripts/auto-replies, recipient reads/failed sends and browser agents.
Use identical wording across different actors and varied wording within actors.
Retain external/uninstrumented agent positives even when telemetry is unavailable.

For each case supply the received synthetic EML, a completed-send action record
or credible operator statement, rights/permission, original collection/expiry,
and actual captured metadata/source frames. Preserve unavailable fields as
unavailable. A packet contains only selected headers/metadata and captured source
evidence, never labels/reviews/filenames/current Outlook categories. JSON does not
authenticate its own source: a curator must verify capture custody and action
records against the original external system. No generated authentication flags.

Use the generated schemas and the runbook in docs/runbooks/sender-accuracy.md.
Assign disjoint sender/workflow/thread/template/source groups across development,
calibration and evaluation; preserve real chronological order. Repeat/copy exports
and reused templates are correlated, not extra independent observations.

An independent curator reviews actual send actions without seeing predictions.
Source-documented sends need a credible independent source review, not two prose
style judgments. Ambiguous/conflicting records need independent adjudication or
remain unresolved. Review files must match the ActionReview schema fields excluding
its attestation asset; record actual reviewed time and hashes, never invented ones.

The owner previously named Kaushik and Rohan; their existing wording judgments
are not completed send-action review or curator acceptance. Ask them to complete
real records under separately controlled access if they take those roles.

Curator owns originals, separate key and one-use evaluation receipts under an OS
account distinct from detector development. Export only development/calibration
to developers, freeze code/policy, then seal and release evaluation exactly once.
Administrator/curator are trusted; same-operator drills do not establish separation.

Raw data retention is seven days from original collection, including imported and
encrypted copies. Reports are private decision metadata with a thirty-day limit;
physical purge/backup operations remain the later operational phase. Collect a
qualification batch within these deadlines; importing does not restart retention.

G1: one-sided 95% exact upper FPR <=0.1% over the enabled AI-rule union, including
ordinary automation. 3,000 independent zero-error negatives is one sufficient case.
G2: >=99% observed supported-path recall over >=1,000 independent agent positives.
Unknown/pending/Human known agents count as misses. All-path recall and
the frozen two-hour / twenty-four-hour results must be reported separately.
Underpowered pilots and authored examples cannot qualify production accuracy.
"""


def prepare_collection(destination: Path) -> None:
    destination.mkdir(mode=0o700, parents=True, exist_ok=False)
    (destination / "README.md").write_text(GUIDE, encoding="utf-8")
    (destination / "collection.csv").write_text(
        "case_ref,received_eml,action_record,rights_record,actual_actor,approval,original_collected_at,expires_at,source_time,route,source_family,split,sender_group,workflow_group,thread_group,template_group,source_group,independence_cluster,curator_review_file\n",
        encoding="utf-8",
    )
    write_new(destination / "dataset.schema.json", AccuracyDataset.model_json_schema())
    write_new(destination / "detector-packet.schema.json", DetectorPacket.model_json_schema())
    write_new(
        destination / "code-policy-freeze.json",
        {
            "detector_sha256": detector_digest(),
            "policy_sha256": policy_digest(),
            "actual_independent_cases": 0,
            "actual_curator_access_verified": False,
            "release_accuracy_qualified": False,
        },
    )
