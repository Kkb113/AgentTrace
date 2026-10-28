"""Bound untrusted MIME structure before recursive email-body helpers run."""

from email import policy
from email.message import EmailMessage
from email.parser import BytesParser

from .validation import InputError

MAX_MIME_DEPTH = 32
MAX_MIME_PARTS = 256


def parse_mime(raw: bytes) -> EmailMessage:
    try:
        message = BytesParser(policy=policy.default).parsebytes(raw)
    except RecursionError as exc:
        raise InputError("mime_structure_limit_exceeded") from exc
    pending = [(message, 0)]
    part_count = 0
    while pending:
        part, depth = pending.pop()
        part_count += 1
        if depth > MAX_MIME_DEPTH or part_count > MAX_MIME_PARTS:
            raise InputError("mime_structure_limit_exceeded")
        if part.is_multipart():
            pending.extend((child, depth + 1) for child in part.iter_parts())
    return message
