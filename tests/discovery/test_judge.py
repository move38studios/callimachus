"""Tests for the judge module — stub-based unit tests + live LLM smoke."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from callimachus.discovery.judge import (
    MAX_ABSTRACT_CHARS,
    Verdict,
    judge_candidate,
    make_default_judge,
    render_judge_prompt,
)
from callimachus.sources.protocols import Provenance, WorkCandidate


def _candidate(
    *,
    title: str = "Denoising Diffusion Probabilistic Models",
    source_url: str = "https://arxiv.org/abs/2006.11239",
    abstract: str | None = "We present diffusion probabilistic models, a class of latent variable…",
    year: int | None = 2020,
    authors: list[str] | None = None,
) -> WorkCandidate:
    return WorkCandidate(
        title=title,
        source_url=source_url,
        provenance=Provenance(source_name="arxiv", query="diffusion"),
        authors=authors or ["Jonathan Ho", "Ajay Jain", "Pieter Abbeel"],
        year=year,
        abstract=abstract,
    )


# ---------- Verdict schema ----------


def test_verdict_validates_score_range() -> None:
    Verdict(accept=True, score=0.0, reasoning="ok ok ok ok")
    Verdict(accept=True, score=1.0, reasoning="ok ok ok ok")
    with pytest.raises(ValidationError):
        Verdict(accept=True, score=1.5, reasoning="ok ok ok ok")
    with pytest.raises(ValidationError):
        Verdict(accept=False, score=-0.1, reasoning="ok ok ok ok")


def test_verdict_requires_min_reasoning_length() -> None:
    with pytest.raises(ValidationError):
        Verdict(accept=True, score=0.8, reasoning="ok")


# ---------- render_judge_prompt ----------


def test_render_judge_prompt_includes_topic_and_key_fields() -> None:
    cand = _candidate()
    prompt = render_judge_prompt("diffusion models", cand)
    assert "Topic: diffusion models" in prompt
    assert cand.title in prompt
    assert "Jonathan Ho" in prompt
    assert "2020" in prompt
    assert cand.source_url in prompt
    assert "Origin plugin: arxiv" in prompt
    assert cand.abstract is not None
    assert cand.abstract[:50] in prompt


def test_render_judge_prompt_truncates_long_abstract() -> None:
    long_abstract = "x" * (MAX_ABSTRACT_CHARS * 2)
    cand = _candidate(abstract=long_abstract)
    prompt = render_judge_prompt("topic", cand)
    # Long abstract must be capped (with an ellipsis marker)
    assert "x" * (MAX_ABSTRACT_CHARS * 2) not in prompt
    assert "…" in prompt


def test_render_judge_prompt_handles_missing_optional_fields() -> None:
    cand = WorkCandidate(
        title="Bare candidate",
        source_url="https://example.com/x",
        provenance=Provenance(source_name="serper_web", query="x"),
        kind="essay",
    )
    prompt = render_judge_prompt("topic", cand)
    assert "Bare candidate" in prompt
    assert "Authors:" not in prompt  # we don't write the key when empty
    assert "Year:" not in prompt
    assert "Abstract:" not in prompt  # nothing to render
    assert "Kind: essay" in prompt  # non-paper kinds are surfaced


def test_render_judge_prompt_surfaces_cited_by_count() -> None:
    cand = _candidate()
    cand.extras["cited_by_count"] = 8123
    prompt = render_judge_prompt("topic", cand)
    assert "Cited by: 8123" in prompt


# ---------- judge_candidate ----------


async def test_judge_candidate_calls_stub_with_topic_and_candidate() -> None:
    seen: dict[str, object] = {}

    async def stub(topic: str, candidate: WorkCandidate) -> Verdict:
        seen["topic"] = topic
        seen["candidate"] = candidate
        return Verdict(accept=True, score=0.9, reasoning="seminal paper for this topic", notes=None)

    cand = _candidate()
    verdict = await judge_candidate("diffusion models", cand, judge_fn=stub)
    assert verdict.accept is True
    assert verdict.score == 0.9
    assert seen["topic"] == "diffusion models"
    assert seen["candidate"] is cand


async def test_judge_candidate_auto_rejects_missing_title() -> None:
    cand = WorkCandidate(
        title="   ",
        source_url="https://x",
        provenance=Provenance(source_name="p", query="q"),
    )

    async def stub(topic: str, candidate: WorkCandidate) -> Verdict:
        del topic, candidate
        msg = "stub should not be called for auto-rejected candidate"
        raise AssertionError(msg)

    verdict = await judge_candidate("topic", cand, judge_fn=stub)
    assert verdict.accept is False
    assert verdict.score == 0.0
    assert "missing title" in verdict.reasoning.lower()


async def test_judge_candidate_auto_rejects_missing_source_url() -> None:
    cand = WorkCandidate(
        title="A title",
        source_url="",
        provenance=Provenance(source_name="p", query="q"),
    )

    async def stub(topic: str, candidate: WorkCandidate) -> Verdict:
        del topic, candidate
        msg = "stub should not be called for auto-rejected candidate"
        raise AssertionError(msg)

    verdict = await judge_candidate("topic", cand, judge_fn=stub)
    assert verdict.accept is False
    assert "source url" in verdict.reasoning.lower()


async def test_judge_candidate_raises_on_empty_topic() -> None:
    cand = _candidate()

    async def stub(topic: str, candidate: WorkCandidate) -> Verdict:
        del topic, candidate
        return Verdict(accept=True, score=1.0, reasoning="should not be called")

    with pytest.raises(ValueError, match="topic"):
        await judge_candidate("   ", cand, judge_fn=stub)


# ---------- live test ----------


@pytest.mark.live
async def test_live_judge_accepts_on_topic_paper() -> None:
    """Hit a real LLM and verify the verdict matches obvious ground truth."""
    judge_fn = make_default_judge()
    cand = _candidate()
    verdict = await judge_fn("denoising diffusion models for image generation", cand)
    assert verdict.accept is True
    assert verdict.score >= 0.5


@pytest.mark.live
async def test_live_judge_rejects_off_topic_paper() -> None:
    judge_fn = make_default_judge()
    cand = _candidate(
        title="A Faster Algorithm for the All-Pairs Shortest Paths Problem in Dense Graphs",
        abstract="We give an O(n^2 log n) algorithm for the APSP problem in dense graphs.",
    )
    verdict = await judge_fn("denoising diffusion models for image generation", cand)
    assert verdict.accept is False
    assert verdict.score <= 0.4
