"""Tests for the enrich stage."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from callimachus.pipeline.enrich import (
    Enrichment,
    enrich_to_files,
    prepend_frontmatter,
    render_yaml_frontmatter,
    strip_frontmatter,
)
from callimachus.pipeline.paths import markdown_path, work_dir


def _make_enrichment() -> Enrichment:
    return Enrichment(
        title="Denoising Diffusion Probabilistic Models",
        authors=["Jonathan Ho", "Ajay Jain", "Pieter Abbeel"],
        year=2020,
        venue="NeurIPS",
        summary=(
            "DDPM presents diffusion probabilistic models as a practical class of "
            "generative models, training via a weighted variational bound that "
            "connects them to denoising score matching with Langevin dynamics."
        ),
        key_claims=[
            "A weighted variational bound is the right training objective for diffusion models.",
            "Diffusion models match GAN sample quality on CIFAR-10 and LSUN.",
        ],
        methods=["denoising diffusion", "variational bound", "Langevin dynamics"],
        datasets=["CIFAR-10", "LSUN"],
        keywords=[
            "diffusion probabilistic models",
            "denoising score matching",
            "variational bound",
            "image generation",
        ],
    )


def _seed_paper_md(library_root: Path, work_id: str, content: str) -> Path:
    path = markdown_path(library_root, work_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


# ---------- Enrichment schema ----------


def test_enrichment_minimal_fields() -> None:
    e = Enrichment(title="x", summary="A reasonable summary that is long enough.")
    assert e.authors == []
    assert e.year is None
    assert e.venue is None
    assert e.key_claims == []
    assert e.methods == []
    assert e.datasets == []
    assert e.keywords == []


def test_enrichment_summary_minimum_length_enforced() -> None:
    with pytest.raises(ValueError, match=r"at least 20"):
        Enrichment(title="x", summary="too short")


# ---------- frontmatter helpers ----------


def test_render_yaml_frontmatter_round_trips() -> None:
    e = _make_enrichment()
    rendered = render_yaml_frontmatter(e)
    assert rendered.startswith("---\n")
    assert rendered.endswith("---\n\n")
    body = rendered[len("---\n") : -len("---\n\n")]
    parsed = yaml.safe_load(body)
    assert parsed["title"] == e.title
    assert parsed["authors"] == e.authors
    assert parsed["year"] == 2020
    assert parsed["venue"] == "NeurIPS"
    assert parsed["datasets"] == ["CIFAR-10", "LSUN"]


def test_render_yaml_frontmatter_includes_null_fields() -> None:
    e = Enrichment(title="x", summary="A summary that is long enough to validate.")
    rendered = render_yaml_frontmatter(e)
    body = rendered[len("---\n") : -len("---\n\n")]
    parsed = yaml.safe_load(body)
    assert parsed["year"] is None
    assert parsed["venue"] is None


def test_render_yaml_frontmatter_handles_unicode() -> None:
    e = Enrichment(
        title="Le café est très bon",
        authors=["François Müller"],
        summary="A reasonable summary that is long enough to clear validation.",
    )
    rendered = render_yaml_frontmatter(e)
    assert "François Müller" in rendered
    assert "Le café est très bon" in rendered


def test_strip_frontmatter_removes_leading_block() -> None:
    md = "---\ntitle: x\nyear: 2020\n---\n\nThe body of the document.\n"
    assert strip_frontmatter(md) == "The body of the document.\n"


def test_strip_frontmatter_no_frontmatter_returns_unchanged() -> None:
    md = "Just body text.\n\nMore body.\n"
    assert strip_frontmatter(md) == md


def test_strip_frontmatter_handles_unclosed_block() -> None:
    """Malformed input — leave it alone rather than mangle it."""
    md = "---\ntitle: x\n\nNo closing fence here.\n"
    assert strip_frontmatter(md) == md


def test_prepend_frontmatter_on_bare_markdown() -> None:
    e = _make_enrichment()
    md = "Body text only.\n"
    result = prepend_frontmatter(md, e)
    assert result.startswith("---\n")
    assert "Body text only." in result


def test_prepend_frontmatter_replaces_existing_frontmatter() -> None:
    e = _make_enrichment()
    md = "---\ntitle: stale title\n---\n\nThe real body.\n"
    result = prepend_frontmatter(md, e)
    assert "stale title" not in result
    assert "Denoising Diffusion" in result
    assert "The real body." in result


def test_prepend_frontmatter_is_idempotent_after_two_runs() -> None:
    e = _make_enrichment()
    md = "Body.\n"
    once = prepend_frontmatter(md, e)
    twice = prepend_frontmatter(once, e)
    assert once == twice


# ---------- enrich_to_files end-to-end ----------


async def test_enrich_to_files_writes_all_three_outputs(tmp_path: Path) -> None:
    work_id = "ho-2020-ddpm"
    body = "# Original title\n\nSome body text from the extracted paper.\n"
    md_path = _seed_paper_md(tmp_path, work_id, body)

    canned = _make_enrichment()

    async def stub_enrich(text: str) -> Enrichment:
        # The function should pass the paper text to the enricher
        assert "extracted paper" in text
        return canned

    result = await enrich_to_files(tmp_path, work_id, enrich_fn=stub_enrich)

    assert result == canned

    # metadata.yaml
    metadata_path = work_dir(tmp_path, work_id) / "metadata.yaml"
    parsed = yaml.safe_load(metadata_path.read_text())
    assert parsed["title"] == canned.title
    assert parsed["authors"] == canned.authors

    # summary.md
    summary_path = work_dir(tmp_path, work_id) / "summary.md"
    assert canned.summary in summary_path.read_text()

    # paper.md now has frontmatter + original body
    updated = md_path.read_text()
    assert updated.startswith("---\n")
    assert "Some body text from the extracted paper." in updated


async def test_enrich_to_files_replaces_existing_frontmatter(tmp_path: Path) -> None:
    """Re-running enrichment should refresh frontmatter, not stack."""
    work_id = "x"
    initial = "---\ntitle: stale\n---\n\nBody.\n"
    md_path = _seed_paper_md(tmp_path, work_id, initial)

    canned = _make_enrichment()

    async def stub(text: str) -> Enrichment:
        del text
        return canned

    await enrich_to_files(tmp_path, work_id, enrich_fn=stub)

    final = md_path.read_text()
    assert final.count("---\n") == 2  # opening + closing fence, exactly once
    assert "stale" not in final
    assert canned.title in final


async def test_enrich_to_files_raises_when_paper_md_missing(tmp_path: Path) -> None:
    async def stub(text: str) -> Enrichment:
        del text
        return _make_enrichment()

    with pytest.raises(FileNotFoundError, match=r"paper\.md not found"):
        await enrich_to_files(tmp_path, "missing", enrich_fn=stub)


async def test_enrich_to_files_raises_when_paper_md_empty(tmp_path: Path) -> None:
    work_id = "x"
    _seed_paper_md(tmp_path, work_id, "   \n  \n")

    async def stub(text: str) -> Enrichment:
        del text
        return _make_enrichment()

    with pytest.raises(ValueError, match="is empty"):
        await enrich_to_files(tmp_path, work_id, enrich_fn=stub)


async def test_enrich_to_files_truncates_oversized_input(tmp_path: Path) -> None:
    """Inputs over MAX_INPUT_CHARS get sliced; the enricher only sees the head."""
    from callimachus.pipeline.enrich import MAX_INPUT_CHARS

    work_id = "huge"
    big_body = "x" * (MAX_INPUT_CHARS + 50_000)
    _seed_paper_md(tmp_path, work_id, big_body)

    seen_lengths: list[int] = []

    async def stub(text: str) -> Enrichment:
        seen_lengths.append(len(text))
        return _make_enrichment()

    await enrich_to_files(tmp_path, work_id, enrich_fn=stub)
    assert seen_lengths == [MAX_INPUT_CHARS]
