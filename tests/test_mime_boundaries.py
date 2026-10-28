from __future__ import annotations

import unittest

from agenttrace_feasibility.mime import MAX_MIME_DEPTH, MAX_MIME_PARTS, parse_mime
from agenttrace_feasibility.validation import InputError


class MimeBoundaryTests(unittest.TestCase):
    def test_normal_plain_text_is_available(self):
        message = parse_mime(b"Content-Type: text/plain; charset=utf-8\r\n\r\nSynthetic text.")
        self.assertEqual(message.get_content(), "Synthetic text.")

    def test_deep_mime_is_rejected_before_body_selection(self):
        raw = b"Content-Type: text/plain\r\n\r\nSynthetic text.\r\n"
        for index in range(MAX_MIME_DEPTH + 2):
            boundary = f"part-{index}".encode()
            raw = (
                b'Content-Type: multipart/mixed; boundary="'
                + boundary
                + b'"\r\n\r\n--'
                + boundary
                + b"\r\n"
                + raw
                + b"\r\n--"
                + boundary
                + b"--\r\n"
            )
        with self.assertRaisesRegex(InputError, "mime_structure_limit_exceeded"):
            parse_mime(raw)

    def test_many_parts_are_rejected(self):
        raw = (
            b'Content-Type: multipart/mixed; boundary="part"\r\n\r\n'
            + b"--part\r\nContent-Type: text/plain\r\n\r\nSynthetic.\r\n" * MAX_MIME_PARTS
            + b"--part--\r\n"
        )
        with self.assertRaisesRegex(InputError, "mime_structure_limit_exceeded"):
            parse_mime(raw)
