"""Bounded, offline normalization entry point. No URL or remote resource loading."""

from agenttrace_feasibility.mime import parse_mime

from .extraction import EXTRACTION_VERSION, BodyExtractor, Extraction

__all__ = ["EXTRACTION_VERSION", "BodyExtractor", "Extraction", "plain_text"]


def plain_text(raw: bytes) -> str | None:
    if len(raw) > 2 * 1024 * 1024:
        raise ValueError("mime_input_too_large")
    message = parse_mime(raw)
    part = message.get_body(preferencelist=("plain",))
    if part is None:
        return None
    content = part.get_content()
    return content if isinstance(content, str) else None
