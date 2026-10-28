"""Operator-only review of group-scoped incremental deployment previews."""


def review_changes(preview: dict, existing_resources: list[dict], group_id: str) -> None:
    prefix = group_id.lower().rstrip("/") + "/"
    existing = {resource["id"].lower(): resource for resource in existing_resources}
    for change in preview.get("changes", []):
        kind, target = change["changeType"], change["resourceId"].lower()
        if kind == "Delete":
            raise ValueError("deployment_deletion_forbidden")
        if kind in {"Ignore", "NoChange"}:
            continue
        if kind not in {"Create", "Modify", "Deploy"} or not target.startswith(prefix):
            raise ValueError("deployment_change_outside_reviewed_group")
        parents = [
            resource
            for identity, resource in existing.items()
            if target == identity or target.startswith(identity + "/")
        ]
        if any(resource.get("tags", {}).get("project") != "AgentTrace" for resource in parents):
            raise ValueError("shared_resource_modification_forbidden")
