"""Tests for the scout module (LLM hypothesis + deterministic probe)."""

from __future__ import annotations

import pytest

from callimachus.discovery.scout import (
    DEFAULT_PROBE_SOURCE,
    _AngleHypothesis,  # pyright: ignore[reportPrivateUsage]
    _ScoutHypothesis,  # pyright: ignore[reportPrivateUsage]
    render_angle_tree,
    run_scout,
)
from callimachus.sources.protocols import (
    Provenance,
    SourceKind,
    SourceUnavailable,
    WorkCandidate,
    WorkKind,
)
from callimachus.sources.registry import SourceRegistry

# ---------- stub source ----------


class StubSource:
    """A DiscoverySource fixture for scout probing."""

    name: str
    kind: SourceKind
    enabled: bool = True

    def __init__(
        self,
        *,
        name: str,
        results: list[WorkCandidate] | None = None,
        raise_unavailable: bool = False,
    ) -> None:
        self.name = name
        self.kind = "bibliographic"
        self._results = results or []
        self._raise = raise_unavailable
        self.calls: list[str] = []

    async def search(
        self,
        query: str,
        *,
        limit: int = 50,
        year_from: int | None = None,
        year_to: int | None = None,
        kinds: list[WorkKind] | None = None,
    ) -> list[WorkCandidate]:
        del limit, year_from, year_to, kinds
        self.calls.append(query)
        if self._raise:
            raise SourceUnavailable(f"{self.name}: stub error")
        return list(self._results)


def _make_candidate(title: str) -> WorkCandidate:
    return WorkCandidate(
        title=title,
        source_url=f"https://example.com/{title.replace(' ', '-')}",
        provenance=Provenance(source_name="stub", query="seed"),
    )


# ---------- run_scout (probe stage) ----------


def _hypothesis(num_angles: int = 5) -> _ScoutHypothesis:
    return _ScoutHypothesis(
        angles=[
            _AngleHypothesis(
                name=f"angle{i}",
                description=f"description for angle {i} long enough to validate",
                keywords=[f"kw{i}a", f"kw{i}b"],
            )
            for i in range(num_angles)
        ],
        related_fields=["adjacent"],
        notes="some notes",
    )


async def test_run_scout_probes_each_angle_against_probe_source() -> None:
    """Each hypothesis angle should produce one source.search() call."""
    source = StubSource(
        name="openalex",
        results=[_make_candidate("p1"), _make_candidate("p2"), _make_candidate("p3")],
    )
    registry = SourceRegistry()
    registry.register_discovery(source)

    tree = await run_scout(
        topic="diffusion",
        registry=registry,
        hypothesis_override=_hypothesis(num_angles=5),
    )

    assert tree.topic == "diffusion"
    assert len(tree.angles) == 5
    assert len(source.calls) == 5
    assert tree.probe_source == DEFAULT_PROBE_SOURCE
    assert tree.related_fields == ["adjacent"]
    # Every angle should carry sample titles from the probe
    for angle in tree.angles:
        assert angle.hit_count == 3
        assert "p1" in angle.sample_titles


async def test_run_scout_swallows_per_angle_source_unavailable() -> None:
    """One angle's probe failing should not crash the scout — the angle gets no evidence."""
    source = StubSource(name="openalex", raise_unavailable=True)
    registry = SourceRegistry()
    registry.register_discovery(source)

    tree = await run_scout(
        topic="x",
        registry=registry,
        hypothesis_override=_hypothesis(num_angles=5),
    )
    assert len(tree.angles) == 5
    for angle in tree.angles:
        assert angle.hit_count == 0
        assert angle.sample_titles == []


async def test_run_scout_probe_source_missing_returns_angles_without_evidence() -> None:
    """If the probe source isn't in the registry, scout still returns the hypothesis angles."""
    registry = SourceRegistry()
    # No source registered
    tree = await run_scout(
        topic="x",
        registry=registry,
        hypothesis_override=_hypothesis(num_angles=5),
    )
    assert len(tree.angles) == 5
    assert all(a.hit_count == 0 for a in tree.angles)
    assert all(a.sample_titles == [] for a in tree.angles)


async def test_run_scout_raises_on_empty_topic() -> None:
    registry = SourceRegistry()
    with pytest.raises(ValueError, match="topic"):
        await run_scout(
            topic="   ",
            registry=registry,
            hypothesis_override=_hypothesis(),
        )


# ---------- LLM-call path via TestModel ----------


async def test_run_scout_full_path_with_test_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exercise the LLM-call path end-to-end with TestModel feeding a hypothesis."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "dummy-for-construction")
    from pydantic_ai.models.test import TestModel

    from callimachus.discovery.scout import make_scout_agent

    source = StubSource(name="openalex", results=[_make_candidate("p1")])
    registry = SourceRegistry()
    registry.register_discovery(source)

    agent = make_scout_agent()
    test_model = TestModel(
        custom_output_args={
            "angles": [
                {
                    "name": "foundations",
                    "description": "seminal pre-2020 work in this area",
                    "keywords": ["x", "y"],
                },
                {
                    "name": "recent",
                    "description": "state of the art after 2022",
                    "keywords": ["a", "b"],
                },
                {
                    "name": "applications",
                    "description": "real-world deployments and case studies",
                    "keywords": ["m", "n"],
                },
                {
                    "name": "criticism",
                    "description": "critiques and alternative framings",
                    "keywords": ["u", "v"],
                },
                {
                    "name": "tooling",
                    "description": "software, datasets, benchmarks",
                    "keywords": ["k", "l"],
                },
            ],
            "related_fields": ["adjacent"],
            "notes": "good coverage requires a sub-area expert",
        }
    )

    with agent.override(model=test_model):
        tree = await run_scout(
            topic="diffusion models",
            registry=registry,
            scout_agent=agent,
        )

    assert len(tree.angles) == 5
    # Each angle was probed once
    assert len(source.calls) == 5


# ---------- render_angle_tree ----------


def test_render_angle_tree_lists_angles_with_hits_and_samples() -> None:
    from callimachus.discovery.plan import Angle, AngleTree

    tree = AngleTree(
        topic="diffusion",
        angles=[
            Angle(
                name="foundations",
                description="pre-2020 seminal work",
                keywords=["DDPM", "Sohl-Dickstein"],
                sample_titles=["Denoising Diffusion Probabilistic Models"],
                hit_count=5,
            ),
        ],
        related_fields=["normalizing flows"],
        notes="lots of overlap with score-matching",
    )
    output = render_angle_tree(tree)
    assert "Topic: diffusion" in output
    assert "foundations" in output
    assert "DDPM" in output
    assert "5 hits" in output
    assert "Denoising Diffusion Probabilistic Models" in output
    assert "normalizing flows" in output
    assert "lots of overlap" in output


def test_render_angle_tree_plain_has_no_rich_markup() -> None:
    from callimachus.discovery.plan import Angle, AngleTree

    tree = AngleTree(topic="x", angles=[Angle(name="a", description="ok ok ok")])
    assert "[bold]" not in render_angle_tree(tree)
    assert "[bold]" in render_angle_tree(tree, color=True)


# ---------- live ----------


@pytest.mark.live
async def test_live_scout_against_openalex() -> None:
    """End-to-end: LLM-generated angles + real OpenAlex probe."""
    from callimachus.sources.bundled.openalex import OpenAlexPlugin

    registry = SourceRegistry()
    registry.register_discovery(OpenAlexPlugin())

    tree = await run_scout(topic="diffusion models for image generation", registry=registry)
    assert tree.topic == "diffusion models for image generation"
    assert len(tree.angles) >= 5
    # At least one angle should have probe evidence
    assert any(a.hit_count > 0 for a in tree.angles)
    assert any(a.sample_titles for a in tree.angles)
