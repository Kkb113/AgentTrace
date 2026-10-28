import importlib.util
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[2] / "scripts/deployment_review.py"
SPEC = importlib.util.spec_from_file_location("deployment_review", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
GROUP = "/subscriptions/synthetic/resourceGroups/kb-agentdemo"


@pytest.mark.parametrize(
    "kind,target,existing",
    [
        ("Delete", GROUP + "/providers/resource/owned", []),
        ("Create", "/subscriptions/other/resourceGroups/unapproved/providers/resource/new", []),
        (
            "Modify",
            GROUP + "/providers/resource/shared",
            [{"id": GROUP + "/providers/resource/shared"}],
        ),
        (
            "Create",
            GROUP + "/providers/resource/shared/diagnostics/new",
            [{"id": GROUP + "/providers/resource/shared"}],
        ),
    ],
)
def test_deployment_review_rejects_deletion_and_shared_or_out_of_group_mutation(
    kind, target, existing
):
    with pytest.raises(ValueError):
        MODULE.review_changes(
            {"changes": [{"changeType": kind, "resourceId": target}]}, existing, GROUP
        )


def test_deployment_review_accepts_own_resource_update_and_ignores_shared_resources():
    owned = GROUP + "/providers/resource/owned"
    MODULE.review_changes(
        {
            "changes": [
                {"changeType": "Modify", "resourceId": owned},
                {"changeType": "Ignore", "resourceId": GROUP + "/providers/resource/shared"},
            ]
        },
        [{"id": owned, "tags": {"project": "AgentTrace"}}],
        GROUP,
    )
