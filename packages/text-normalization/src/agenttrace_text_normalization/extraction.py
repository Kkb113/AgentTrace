"""Bounded offline body extraction with decoded-source offsets and explicit omissions."""

from __future__ import annotations

import html
import re
import unicodedata
from dataclasses import dataclass, field
from email import policy
from email.parser import BytesParser
from html.parser import HTMLParser
from typing import Literal

from .language import EnglishIdentifier

EXTRACTION_VERSION = "text-extraction/1.0"
RegionKind = Literal["authored", "quoted", "signature", "boilerplate", "ambiguous"]


@dataclass(frozen=True)
class SourceOffset:
    normalized_start: int
    normalized_end: int
    source_start: int
    source_end: int


@dataclass(frozen=True)
class TextRegion:
    start: int
    end: int
    kind: RegionKind
    quote_depth: int = 0


@dataclass(frozen=True)
class Extraction:
    status: Literal["extracted", "unavailable", "ambiguous"]
    normalized_text: str = field(repr=False)
    authored_text: str = field(repr=False)
    regions: tuple[TextRegion, ...]
    offsets: tuple[SourceOffset, ...]
    reasons: tuple[str, ...]
    language: str
    authored_words: int
    word_bin: str
    statistically_eligible: bool
    excluded_attachment_count: int = 0
    version: str = EXTRACTION_VERSION
    offset_coordinate: str = "unicode_codepoints_in_decoded_body_part"

    def summary(self) -> dict[str, object]:
        return {
            "status": self.status,
            "normalization_version": self.version,
            "language": self.language,
            "authored_words": self.authored_words,
            "word_bin": self.word_bin,
            "statistically_eligible": self.statistically_eligible,
            "region_counts": {
                kind: sum(r.kind == kind for r in self.regions)
                for kind in ("authored", "quoted", "signature", "boilerplate", "ambiguous")
            },
            "reasons": list(self.reasons),
            "excluded_attachment_count": self.excluded_attachment_count,
            "offset_coordinate": self.offset_coordinate,
            "scorer_state": "not_installed",
        }


@dataclass(frozen=True)
class _Character:
    value: str
    start: int
    end: int
    depth: int = 0


class _OfflineHTML(HTMLParser):
    BLOCKS = {"p", "div", "section", "article", "li", "tr", "br", "blockquote", "hr", "pre"}
    OMIT = {
        "script",
        "style",
        "noscript",
        "template",
        "iframe",
        "object",
        "svg",
        "head",
        "video",
        "audio",
    }
    VOID = {
        "br",
        "hr",
        "img",
        "meta",
        "link",
        "input",
        "source",
        "wbr",
        "area",
        "base",
        "embed",
        "param",
        "track",
        "col",
    }

    def __init__(self, source: str):
        super().__init__(convert_charrefs=False)
        self.source = source
        self.lines = [0, *[m.end() for m in re.finditer("\n", source)]]
        self.stack: list[tuple[str, bool, bool]] = []
        self.output: list[_Character] = []
        self.reasons: set[str] = set()

    def _position(self) -> int:
        line, column = self.getpos()
        return self.lines[line - 1] + column

    def _emit(self, text: str, start: int, end: int) -> None:
        if any(hidden for _, hidden, _ in self.stack):
            return
        depth = sum(quoted for _, _, quoted in self.stack)
        self.output.extend(_Character(char, start, end, depth) for char in text)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if len(self.stack) >= 128:
            raise ValueError("html_nesting_limit")
        start = self._position()
        end = start + len(self.get_starttag_text() or "")
        attributes = {key.lower(): value or "" for key, value in attrs}
        style = re.sub(r"\s+", "", attributes.get("style", "").lower())
        hidden = (
            tag in self.OMIT
            or "hidden" in attributes
            or attributes.get("aria-hidden") == "true"
            or "display:none" in style
            or "visibility:hidden" in style
        )
        quoted = tag == "blockquote" or any(
            marker in attributes.get("class", "").lower()
            for marker in ["gmail_quote", "yahoo_quoted", "ms-outlook-mobile-reference-message"]
        )
        if hidden:
            self.reasons.add("active_or_hidden_html_omitted")
        if tag == "img":
            self.reasons.add("remote_or_embedded_image_omitted")
        if tag in self.BLOCKS:
            self._emit("\n", start, end)
        if tag not in self.VOID:
            self.stack.append((tag, hidden, quoted))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag in self.VOID:
            return
        found = next(
            (i for i in range(len(self.stack) - 1, -1, -1) if self.stack[i][0] == tag), None
        )
        if found is None:
            self.reasons.add("malformed_html_structure")
            return
        if found != len(self.stack) - 1:
            self.reasons.add("malformed_html_structure")
        start = self._position()
        end = self.source.find(">", start)
        if tag in self.BLOCKS:
            self._emit("\n", start, end + 1 if end >= 0 else start)
        del self.stack[found:]

    def handle_data(self, data: str) -> None:
        start = self._position()
        if any(hidden for _, hidden, _ in self.stack):
            return
        depth = sum(quoted for _, _, quoted in self.stack)
        self.output.extend(
            _Character(char, start + i, start + i + 1, depth) for i, char in enumerate(data)
        )

    def handle_entityref(self, name: str) -> None:
        start = self._position()
        self._emit(html.unescape("&" + name + ";"), start, start + len(name) + 2)

    def handle_charref(self, name: str) -> None:
        start = self._position()
        self._emit(html.unescape("&#" + name + ";"), start, start + len(name) + 3)


def _normalized(characters: list[_Character]) -> list[_Character]:
    result: list[_Character] = []
    index = 0
    while index < len(characters):
        item = characters[index]
        if unicodedata.category(item.value) in {"Cf", "Cc"} and item.value not in "\n\r\t":
            index += 1
            continue
        end = index + 1
        while end < len(characters) and unicodedata.combining(characters[end].value):
            end += 1
        cluster = characters[index:end]
        text = unicodedata.normalize("NFC", "".join(c.value for c in cluster))
        for char in text:
            value = "\n" if char in "\n\r" else " " if char.isspace() else char
            current = _Character(
                value,
                min(c.start for c in cluster),
                max(c.end for c in cluster),
                max(c.depth for c in cluster),
            )
            if result and value in " \n" and result[-1].value == value:
                previous = result[-1]
                result[-1] = _Character(
                    value,
                    previous.start,
                    max(previous.end, current.end),
                    max(previous.depth, current.depth),
                )
            else:
                result.append(current)
        index = end
    return result


def _regions(characters: list[_Character]) -> tuple[TextRegion, ...]:
    text = "".join(c.value for c in characters)
    regions: list[TextRegion] = []
    inherited = False
    footer: RegionKind | None = None
    for match in re.finditer(r"[^\n]+(?:\n|$)|\n", text):
        line = match.group().strip()
        depth = max((c.depth for c in characters[match.start() : match.end()]), default=0)
        if re.match(
            r"(?i)^(?:[- ]*original message[- ]*|[- ]*forwarded message[- ]*|begin forwarded message:|on .{1,200}wrote:)\s*$",
            line,
        ):
            inherited = True
        if re.match(r"(?i)^from:\s+", line) and re.search(
            r"(?im)^(?:sent|date|to|subject):", text[match.end() : match.end() + 500]
        ):
            inherited = True
        if (
            not inherited
            and not depth
            and re.match(r"^(?:--|Sent from my (?:iPhone|Android)|Get Outlook for .*)\s*$", line)
        ):
            footer = "signature"
        if (
            not inherited
            and not depth
            and re.match(
                r"(?i)^(?:confidentiality notice:|this (?:email|message) (?:and any attachments |is intended)|the information contained in this (?:email|message))",
                line,
            )
        ):
            footer = "boilerplate"
        kind: RegionKind = (
            "quoted" if depth or inherited or line.startswith(">") else footer or "authored"
        )
        actual_depth = max(depth, len(line) - len(line.lstrip(">"))) if kind == "quoted" else 0
        if regions and regions[-1].kind == kind and regions[-1].quote_depth == actual_depth:
            last = regions.pop()
            regions.append(TextRegion(last.start, match.end(), kind, actual_depth))
        else:
            regions.append(TextRegion(match.start(), match.end(), kind, actual_depth))
    return tuple(regions)


class BodyExtractor:
    def __init__(self, identifier: EnglishIdentifier | None = None):
        self.identifier = identifier or EnglishIdentifier()

    def unavailable(self, reason: str, *, attachments: int = 0) -> Extraction:
        return Extraction(
            "unavailable", "", "", (), (), (reason,), "unknown", 0, "0", False, attachments
        )

    def extract(self, source: str, content_type: str, *, attachments: int = 0) -> Extraction:
        if len(source) > 262_144:
            return self.unavailable("body_size_limit", attachments=attachments)
        reasons: set[str] = set()
        if content_type.lower() == "html":
            parser = _OfflineHTML(source)
            try:
                parser.feed(source)
                parser.close()
            except Exception:
                return self.unavailable("html_parse_limit_or_failure", attachments=attachments)
            if parser.stack:
                parser.reasons.add("malformed_html_structure")
            characters = parser.output
            reasons.update(parser.reasons)
        elif content_type.lower() in {"text", "plain", "text/plain"}:
            characters = [_Character(char, index, index + 1) for index, char in enumerate(source)]
        else:
            return self.unavailable("unsupported_body_format", attachments=attachments)
        if any(unicodedata.category(c) == "Cf" for c in source):
            reasons.add("invisible_controls_removed")
        characters = _normalized(characters)
        if len(characters) > 131_072:
            return self.unavailable("normalized_text_size_limit", attachments=attachments)
        normalized = "".join(c.value for c in characters)
        regions = _regions(characters)
        ambiguous = bool(
            reasons.intersection({"malformed_html_structure", "invisible_controls_removed"})
        )
        if ambiguous:
            regions = tuple(
                TextRegion(
                    r.start, r.end, "ambiguous" if r.kind == "authored" else r.kind, r.quote_depth
                )
                for r in regions
            )
        authored = "\n".join(
            normalized[r.start : r.end].strip() for r in regions if r.kind == "authored"
        ).strip()
        count = len(re.findall(r"\b[^\W\d_]+(?:['’-][^\W\d_]+)*\b", authored))
        bin_name = (
            "0"
            if count == 0
            else "1-49"
            if count < 50
            else "50-99"
            if count < 100
            else "100-199"
            if count < 200
            else "200+"
        )
        language = self.identifier.assess(authored)
        reasons.add(language.reason)
        if count < 100:
            reasons.add("below_statistical_length_eligibility")
        if attachments:
            reasons.add("attachments_omitted")
        offset_runs: list[SourceOffset] = []
        for index, character in enumerate(characters):
            if offset_runs and character.end - character.start == 1:
                last = offset_runs[-1]
                if (
                    last.source_end == character.start
                    and last.normalized_end - last.normalized_start
                    == last.source_end - last.source_start
                ):
                    offset_runs[-1] = SourceOffset(
                        last.normalized_start, index + 1, last.source_start, character.end
                    )
                    continue
            offset_runs.append(SourceOffset(index, index + 1, character.start, character.end))
        offsets = tuple(offset_runs)
        return Extraction(
            "ambiguous" if ambiguous else "extracted",
            normalized,
            authored,
            regions,
            offsets,
            tuple(sorted(reasons)),
            language.language,
            count,
            bin_name,
            not ambiguous and language.eligible_language and count >= 100,
            attachments,
        )

    def extract_mime(self, raw: bytes) -> Extraction:
        if len(raw) > 2 * 1024 * 1024:
            return self.unavailable("mime_size_limit")
        try:
            message = BytesParser(policy=policy.default).parsebytes(raw)
            if (
                message.get_content_type() in {"application/pkcs7-mime", "application/x-pkcs7-mime"}
                or message.get_content_type() == "multipart/encrypted"
            ):
                return self.unavailable("protected_or_encrypted_message")
            attachments = sum(part.is_attachment() for part in message.walk())
            part = message.get_body(preferencelist=("plain", "html"))
            if part is None:
                return self.unavailable("no_accessible_body", attachments=attachments)
            value = part.get_content()
            if not isinstance(value, str):
                return self.unavailable("body_decode_failure", attachments=attachments)
            return self.extract(
                value,
                "html" if part.get_content_type() == "text/html" else "text",
                attachments=attachments,
            )
        except Exception:
            return self.unavailable("mime_parse_failure")
