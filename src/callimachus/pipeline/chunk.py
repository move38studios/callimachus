"""Chunk stage — split a paper's markdown into ~512-token chunks with overlap.

Pure recursive paragraph-aware splitter, no LangChain dep.

Strategy (per the 2026 RAG benchmark consensus):
- Target ~2000 chars per chunk (≈ 512 tokens), ~250 char overlap (~12%).
- Split first at paragraph boundaries (double newlines).
- If a paragraph alone exceeds target, split at sentence boundaries.
- If a sentence alone exceeds target, hard-split at chars.
- Track section context: for each chunk, record the most recent heading
  encountered (markdown `#`/`##` or pylatexenc's `§ HEADING` form).

Section is stored as the leaf only (the most recent heading), not the
full path — keeps the contextual prefix short and the schema simple.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from callimachus.pipeline.enrich import strip_frontmatter

DEFAULT_TARGET_CHARS = 2000
DEFAULT_OVERLAP_CHARS = 250

# Match either markdown headings (`# H`, `## H`, …) OR pylatexenc's `§ H`.
HEADING_RE = re.compile(r"^(?:#+|§)\s+(.+?)\s*$")

# Sentence-end split — period/?/! followed by whitespace and a capital
# letter. Doesn't try to be perfect (no "Mr." handling); good enough for
# academic prose.
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z\[(])")


class MarkdownChunk(BaseModel):
    """A piece of paper text headed for the embedder."""

    ord: int = Field(description="0-indexed position within the work.")
    text: str = Field(description="The chunk's plain text — no contextual prefix.")
    section: str | None = Field(
        default=None,
        description="The most recent heading encountered, or None for pre-heading text.",
    )


def _split_paragraph(text: str, target_chars: int) -> list[str]:
    """Split a single oversize paragraph at sentence boundaries, then chars.

    Returns a list of strings each <= target_chars (best effort).
    """
    if len(text) <= target_chars:
        return [text]

    sentences = SENTENCE_SPLIT_RE.split(text)
    out: list[str] = []
    buf = ""
    for sentence in sentences:
        if not sentence:
            continue
        if buf and len(buf) + 1 + len(sentence) > target_chars:
            out.append(buf)
            buf = sentence
        elif buf:
            buf = f"{buf} {sentence}"
        else:
            buf = sentence
    if buf:
        out.append(buf)

    # Anything still over target → hard-split at chars
    final: list[str] = []
    for piece in out:
        if len(piece) <= target_chars:
            final.append(piece)
        else:
            for start in range(0, len(piece), target_chars):
                final.append(piece[start : start + target_chars])
    return final


def _tail(text: str, n: int) -> str:
    """Last `n` chars, broken cleanly at a word boundary if possible."""
    if len(text) <= n:
        return text
    suffix = text[-n:]
    # Walk forward to a whitespace so we don't start the overlap mid-word
    space = suffix.find(" ")
    if 0 <= space < n // 2:  # only if it doesn't trim too much
        return suffix[space + 1 :]
    return suffix


def chunk_markdown(
    markdown: str,
    *,
    target_chars: int = DEFAULT_TARGET_CHARS,
    overlap_chars: int = DEFAULT_OVERLAP_CHARS,
) -> list[MarkdownChunk]:
    """Split markdown text into overlapping chunks with section tracking.

    YAML frontmatter (Jekyll-style `---\\n...\\n---`) is stripped before
    chunking so the body text is what gets indexed.
    """
    if overlap_chars >= target_chars:
        msg = f"overlap_chars ({overlap_chars}) must be < target_chars ({target_chars})"
        raise ValueError(msg)

    body = strip_frontmatter(markdown).strip()
    if not body:
        return []

    # Split into paragraph-like blocks. Track current section as we walk.
    blocks: list[tuple[str | None, str]] = []  # (section, text)
    current_section: str | None = None
    current_lines: list[str] = []

    def _flush_block() -> None:
        if current_lines:
            text = "\n".join(current_lines).strip()
            if text:
                blocks.append((current_section, text))
            current_lines.clear()

    for line in body.splitlines():
        heading_match = HEADING_RE.match(line)
        if heading_match:
            _flush_block()
            current_section = heading_match.group(1).strip()
            continue
        if not line.strip():
            _flush_block()
            continue
        current_lines.append(line)
    _flush_block()

    # Now combine blocks into chunks, respecting target_chars and overlap.
    chunks: list[MarkdownChunk] = []
    buf_section: str | None = None
    buf_text = ""
    ord_counter = 0

    def _emit() -> None:
        nonlocal buf_text, ord_counter
        if not buf_text.strip():
            buf_text = ""
            return
        chunks.append(MarkdownChunk(ord=ord_counter, text=buf_text.strip(), section=buf_section))
        ord_counter += 1
        buf_text = ""

    for section, text in blocks:
        # If a single block exceeds target, pre-split it
        pieces = _split_paragraph(text, target_chars) if len(text) > target_chars else [text]

        for piece in pieces:
            if not buf_text:
                # New chunk starts here; section follows the block
                buf_section = section
                buf_text = piece
                continue

            # If section changed, flush before mixing across sections
            if section != buf_section:
                _emit()
                buf_section = section
                buf_text = piece
                continue

            # If adding this piece would overflow, emit + start new with overlap
            if len(buf_text) + 2 + len(piece) > target_chars:
                # Carry forward overlap_chars of trailing context
                overlap = _tail(buf_text, overlap_chars) if overlap_chars else ""
                _emit()
                buf_section = section
                buf_text = (overlap + "\n\n" + piece).strip() if overlap else piece
                continue

            buf_text = f"{buf_text}\n\n{piece}"

    _emit()
    return chunks
