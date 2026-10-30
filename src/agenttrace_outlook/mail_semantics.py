"""Canonical sender evidence excludes mutable categories and provider change keys."""

from typing import Any


def sender_snapshot(detail: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    headers = detail.get("internetMessageHeaders")
    complete = (
        isinstance(headers, list)
        and bool(headers)
        and len(headers) <= 2000
        and all(
            isinstance(h, dict)
            and isinstance(h.get("name"), str)
            and isinstance(h.get("value"), str)
            for h in (headers or [])
        )
    )
    semantic = {
        k: detail.get(k)
        for k in ("receivedDateTime", "sentDateTime", "internetMessageId", "isDraft")
    }
    semantic["internetMessageHeaders"] = (
        sorted(
            [{"name": h["name"].lower(), "value": h["value"]} for h in (headers or [])],
            key=lambda h: (h["name"], h["value"]),
        )
        if complete
        else None
    )
    return semantic, bool(complete)
