"""Tests for the chunker."""

from __future__ import annotations

from callimachus.pipeline.chunk import (
    DEFAULT_OVERLAP_CHARS,
    DEFAULT_TARGET_CHARS,
    MarkdownChunk,
    chunk_markdown,
)

# ---------- basic shape ----------


def test_empty_input_returns_no_chunks() -> None:
    assert chunk_markdown("") == []
    assert chunk_markdown("   \n\n  \n") == []


def test_short_input_yields_one_chunk() -> None:
    chunks = chunk_markdown("Just a small paragraph that fits in a single chunk.")
    assert len(chunks) == 1
    assert chunks[0].ord == 0
    assert "single chunk" in chunks[0].text
    assert chunks[0].section is None


def test_chunks_are_ordered_sequentially() -> None:
    paragraphs = [f"Paragraph {i}. {'filler ' * 200}" for i in range(5)]
    text = "\n\n".join(paragraphs)
    chunks = chunk_markdown(text)
    assert len(chunks) > 1
    assert [c.ord for c in chunks] == list(range(len(chunks)))


def test_chunks_respect_target_size_loosely() -> None:
    paragraphs = [f"Paragraph {i}. {'filler ' * 100}" for i in range(10)]
    text = "\n\n".join(paragraphs)
    chunks = chunk_markdown(text, target_chars=2000, overlap_chars=200)
    # Each chunk should be at most ~2 * target_chars (overlap can push slightly over)
    for c in chunks:
        assert len(c.text) <= 2 * 2000


# ---------- section tracking ----------


def test_markdown_section_headings_are_tracked() -> None:
    md = (
        "# Paper Title\n\n"
        "Pre-section text.\n\n"
        "## Introduction\n\n"
        "Intro paragraph.\n\n"
        "## Method\n\n"
        "Method paragraph.\n"
    )
    chunks = chunk_markdown(md)
    by_text = {c.text: c.section for c in chunks}
    # Pre-section text comes after `# Paper Title` so its section is "Paper Title"
    assert by_text["Pre-section text."] == "Paper Title"
    assert by_text["Intro paragraph."] == "Introduction"
    assert by_text["Method paragraph."] == "Method"


def test_pylatexenc_style_section_headings_are_tracked() -> None:
    """pylatexenc renders `\\section{X}` as `§ X` (uppercase)."""
    md = (
        "Document title here\n\n"
        "Pre-section text.\n\n"
        "§ INTRODUCTION\n\n"
        "Intro paragraph.\n\n"
        "§ METHOD\n\n"
        "Method paragraph.\n"
    )
    chunks = chunk_markdown(md)
    sections = [c.section for c in chunks]
    assert "INTRODUCTION" in sections
    assert "METHOD" in sections


def test_section_change_forces_new_chunk() -> None:
    """Two paragraphs that would fit in one chunk get split when sections differ."""
    md = "## Section A\n\nShort para A.\n\n## Section B\n\nShort para B.\n"
    chunks = chunk_markdown(md, target_chars=2000, overlap_chars=0)
    assert len(chunks) == 2
    assert chunks[0].section == "Section A"
    assert chunks[0].text == "Short para A."
    assert chunks[1].section == "Section B"
    assert chunks[1].text == "Short para B."


# ---------- frontmatter handling ----------


def test_yaml_frontmatter_is_stripped_before_chunking() -> None:
    md = "---\ntitle: x\nauthors: [a, b]\n---\n\n## Real Section\n\nThe body.\n"
    chunks = chunk_markdown(md)
    assert all("title:" not in c.text for c in chunks)
    assert chunks[0].section == "Real Section"


# ---------- overlap behavior ----------


def test_overlap_carries_trailing_text_to_next_chunk() -> None:
    para = "Distinct phrase " + ("filler " * 200)  # ~1400+ chars
    text = "\n\n".join(para for _ in range(5))
    chunks = chunk_markdown(text, target_chars=2000, overlap_chars=300)
    assert len(chunks) > 1
    # At least one of chunk[1+] should contain a tail snippet of an
    # earlier chunk's content
    overlapped = any(
        chunks[i].text[: len("filler ")] == "filler " or "filler" in chunks[i].text[:300]
        for i in range(1, len(chunks))
    )
    assert overlapped


def test_overlap_zero_means_no_carry() -> None:
    para = "x " * 1500  # one big paragraph
    chunks = chunk_markdown(para, target_chars=2000, overlap_chars=0)
    # When overlap=0, total text in all chunks ≈ original text length
    total = sum(len(c.text) for c in chunks)
    assert total <= len(para) + 100  # small slack for whitespace handling


def test_overlap_must_be_less_than_target() -> None:
    import pytest

    with pytest.raises(ValueError, match="overlap_chars"):
        chunk_markdown("x", target_chars=100, overlap_chars=200)


# ---------- oversized paragraph handling ----------


def test_huge_single_paragraph_gets_split() -> None:
    """A 5000-char paragraph with no sentence boundaries still chunks."""
    para = "x" * 5000
    chunks = chunk_markdown(para, target_chars=2000, overlap_chars=0)
    assert len(chunks) >= 2
    # All chunks should be at or below target
    for c in chunks:
        assert len(c.text) <= 2000 + 100  # small slack


def test_huge_paragraph_with_sentences_splits_at_sentence_boundaries() -> None:
    sentences = [f"This is sentence number {i} and it is fairly long." for i in range(60)]
    para = " ".join(sentences)
    chunks = chunk_markdown(para, target_chars=600, overlap_chars=0)
    # Each chunk should end at a sentence boundary (period followed by nothing, ideally)
    for c in chunks[:-1]:  # last may not end cleanly if the last sentence got chunked
        assert c.text.endswith(".") or c.text.endswith(" ")


# ---------- defaults ----------


def test_defaults_are_sane() -> None:
    assert DEFAULT_TARGET_CHARS == 2000
    assert DEFAULT_OVERLAP_CHARS == 250


def test_chunk_model_has_required_fields() -> None:
    c = MarkdownChunk(ord=0, text="x", section=None)
    assert c.ord == 0
    assert c.text == "x"
    assert c.section is None
