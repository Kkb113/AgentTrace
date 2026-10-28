import pytest
from agenttrace_text_normalization import BodyExtractor

from tests.ingestion_support import BODY


@pytest.fixture(scope="module")
def extractor():
    return BodyExtractor()


@pytest.mark.parametrize(
    "body,format,authored,quoted",
    [
        (
            "A new reply.\n> An earlier message.\n>> A nested message.",
            "text",
            "A new reply.",
            "An earlier message.",
        ),
        (
            "A new reply.\nOn Tuesday, Reviewer wrote:\nEarlier text",
            "text",
            "A new reply.",
            "Earlier text",
        ),
        (
            "A new reply.\n-----Original Message-----\nEarlier text",
            "text",
            "A new reply.",
            "Earlier text",
        ),
        (
            "<p>A new reply.</p><blockquote>Earlier text<blockquote>Nested text</blockquote></blockquote>",
            "html",
            "A new reply.",
            "Earlier text",
        ),
        (
            "<p>A new reply.</p><div class='gmail_quote'>Earlier text</div>",
            "html",
            "A new reply.",
            "Earlier text",
        ),
        (
            "A new reply.\nFrom: Reviewer\nSent: Tuesday\nTo: Colleague\nEarlier text",
            "text",
            "A new reply.",
            "Earlier text",
        ),
    ],
)
def test_labeled_reply_and_forward_regions(extractor, body, format, authored, quoted):
    result = extractor.extract(body, format)
    assert result.authored_text == authored
    inherited = "".join(
        result.normalized_text[r.start : r.end] for r in result.regions if r.kind == "quoted"
    )
    assert quoted in inherited
    assert len(inherited) > 0


def test_signatures_disclaimers_and_images_never_inflate_authored_text(extractor):
    result = extractor.extract(
        "New information.\n--\nInvented Person\nConfidentiality notice: " + BODY,
        "text",
        attachments=2,
    )
    assert result.authored_text == "New information."
    assert {r.kind for r in result.regions} == {"authored", "signature", "boilerplate"}
    assert result.authored_words == 2 and not result.statistically_eligible
    assert result.excluded_attachment_count == 2


def test_html_plain_equivalence_and_offsets_for_entities_and_unicode(extractor):
    html = "<p>Review caf&#233; &amp; re\u0301sume\u0301.</p>"
    a = extractor.extract(html, "html")
    b = extractor.extract("Review café & résumé.", "text")
    assert a.authored_text == b.authored_text
    assert a.offsets[0].normalized_start == 0
    assert a.offsets[-1].normalized_end == len(a.normalized_text)
    assert all(0 <= o.source_start <= o.source_end <= len(html) for o in a.offsets)
    for left, right in zip(a.offsets, a.offsets[1:]):
        assert left.normalized_end == right.normalized_start


def test_active_remote_and_hidden_html_is_not_executed_or_read(extractor, monkeypatch):
    import socket

    monkeypatch.setattr(
        socket,
        "create_connection",
        lambda *args, **kwargs: pytest.fail("Extraction attempted network I/O"),
    )
    result = extractor.extract(
        "<p>Visible text</p><script>secret script</script><style>secret style</style><div hidden>hidden secret</div><img src='https://example.invalid/pixel'><iframe src='https://example.invalid'></iframe>",
        "html",
    )
    assert result.authored_text == "Visible text"
    assert "secret" not in result.normalized_text
    assert "remote_or_embedded_image_omitted" in result.reasons


@pytest.mark.parametrize(
    "body,format",
    [("<p>Unclosed", "html"), ("New\u200b text", "text"), ("<div><p>Mismatch</div>", "html")],
)
def test_ambiguity_never_claims_eligible_authored_prose(extractor, body, format):
    result = extractor.extract(body, format)
    assert result.status == "ambiguous" and not result.statistically_eligible
    assert not result.authored_text


@pytest.mark.parametrize(
    "body",
    [
        "El equipo ha terminado la revisión de los documentos y necesita confirmar la próxima reunión. "
        * 10,
        "L'équipe a terminé la révision des documents et doit confirmer la prochaine réunion. "
        * 10,
        "यह केवल एक परीक्षण संदेश है और इसमें किसी ग्राहक की जानकारी नहीं है। " * 10,
        BODY
        + "\n\nEl equipo ha terminado la revisión de los documentos y necesita confirmar la próxima reunión. "
        * 5,
    ],
)
def test_non_english_and_mixed_language_are_unknown(extractor, body):
    result = extractor.extract(body, "text")
    assert result.language == "unknown" and not result.statistically_eligible


def test_english_eligibility_is_not_an_ai_authorship_score(extractor):
    result = extractor.extract(BODY, "text")
    assert result.language == "en" and result.statistically_eligible
    assert result.summary()["scorer_state"] == "not_installed"
    assert "body" not in result.summary() and "score" not in result.summary()


@pytest.mark.parametrize(
    "body,format,reason",
    [
        ("x" * 262145, "text", "body_size_limit"),
        ("hello", "binary", "unsupported_body_format"),
        ("x" * 131073, "text", "normalized_text_size_limit"),
    ],
)
def test_size_and_unsupported_format_failures_are_explicit(extractor, body, format, reason):
    result = extractor.extract(body, format)
    assert result.status == "unavailable" and reason in result.reasons


def test_protected_mime_and_attachments_excluded(extractor):
    protected = b"MIME-Version: 1.0\r\nContent-Type: application/pkcs7-mime\r\n\r\nencrypted"
    assert extractor.extract_mime(protected).reasons == ("protected_or_encrypted_message",)
    normal = (
        b"MIME-Version: 1.0\r\nContent-Type: text/plain; charset=utf-8\r\n\r\nSynthetic example"
    )
    assert extractor.extract_mime(normal).authored_text == "Synthetic example"
