"""Scout — shallow probe of a topic to produce an AngleTree for HITL review.

Two-stage process, biased toward cost + speed:

1. **LLM angle hypothesis** (1 call, Haiku 4.5): given the topic, generate
   5-10 distinct angles + 2-3 keywords each + a few adjacent-field
   suggestions.
2. **Deterministic probe** (~N small API calls in parallel): for each
   angle, run one search against the probe source (default: OpenAlex)
   to back the hypothesis with real evidence — sample titles and hit
   counts the user can calibrate against.

The scout never decides what to keep — it just shows the user what
exists so the ceremony can lock in a Plan.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Literal

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from callimachus.discovery.plan import Angle, AngleTree
from callimachus.llm import MODEL_FAST
from callimachus.sources.protocols import SourceUnavailable
from callimachus.sources.registry import SourceRegistry

log = logging.getLogger(__name__)

DEFAULT_PROBE_SOURCE = "openalex"
DEFAULT_MIN_ANGLES = 5
DEFAULT_MAX_ANGLES = 8
DEFAULT_PER_ANGLE_LIMIT = 6


class _AngleHypothesis(BaseModel):
    """One angle the scout proposes before any probing happens."""

    name: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=10)
    keywords: list[str] = Field(min_length=1, max_length=5)


class _ScoutHypothesis(BaseModel):
    """The LLM's structured first-pass output. Probed downstream."""

    angles: list[_AngleHypothesis] = Field(
        min_length=DEFAULT_MIN_ANGLES, max_length=DEFAULT_MAX_ANGLES
    )
    related_fields: list[str] = Field(
        default_factory=list,
        description="Adjacent topics that share authors/methods but are out of scope.",
    )
    notes: str = Field(
        default="",
        description="Optional 1-2 sentence framing observation for the user.",
    )


SCOUT_SYSTEM_PROMPT = """\
You are a research scout. Given a topic, your job is to map out 5-8 distinct
angles a deep library on the topic should cover.

Rules:
- Each angle must be genuinely distinct — different methods, different sub-fields,
  different eras, or different framings. Don't just rephrase the topic.
- Be specific. "foundations" is fine; "foundations of cognitive science of
  divergent thinking" is better.
- Each angle gets 2-3 search keywords. Keywords should be the terms someone
  would actually use to find papers in this angle (not the angle name verbatim).
- Suggest 2-4 related fields — adjacent topics with shared authors or methods,
  in case the user's real interest is broader than the literal topic.
- Don't pre-judge importance. The user decides.

Return a _ScoutHypothesis with 5-8 angles. Do not search for papers yet —
that happens after you return.
"""


async def _probe_angle(
    angle_idx: int,
    hypothesis: _AngleHypothesis,
    probe_source_name: str,
    registry: SourceRegistry,
    per_angle_limit: int,
) -> Angle:
    """Run one shallow search for an angle and assemble the Angle object."""
    source = registry.get_discovery(probe_source_name)
    if source is None:
        log.debug(
            "scout: probe source %r not registered; returning angle %d " "without sample evidence",
            probe_source_name,
            angle_idx,
        )
        return Angle(
            name=hypothesis.name,
            description=hypothesis.description,
            keywords=hypothesis.keywords,
        )

    query = " ".join(hypothesis.keywords[:3]) or hypothesis.name

    try:
        results = await source.search(query, limit=per_angle_limit)
    except SourceUnavailable as exc:
        log.warning(
            "scout: probe via %r for angle %r failed: %s",
            probe_source_name,
            hypothesis.name,
            exc,
        )
        results = []

    return Angle(
        name=hypothesis.name,
        description=hypothesis.description,
        keywords=hypothesis.keywords,
        sample_titles=[r.title for r in results[: max(3, per_angle_limit // 2)]],
        hit_count=len(results),
    )


def make_scout_agent(model: str = MODEL_FAST) -> Agent[None, _ScoutHypothesis]:
    """Build the angle-hypothesis agent. Public for testing."""
    return Agent(
        model,
        output_type=_ScoutHypothesis,
        system_prompt=SCOUT_SYSTEM_PROMPT,
    )


async def run_scout(
    *,
    topic: str,
    registry: SourceRegistry,
    probe_source: str = DEFAULT_PROBE_SOURCE,
    per_angle_limit: int = DEFAULT_PER_ANGLE_LIMIT,
    model: str = MODEL_FAST,
    scout_agent: Agent[None, _ScoutHypothesis] | None = None,
    hypothesis_override: _ScoutHypothesis | None = None,
) -> AngleTree:
    """Generate an AngleTree for `topic`.

    Args:
        topic: The user's input topic.
        registry: Source registry; must contain the probe source (typically
            'openalex') for the deterministic probe stage.
        probe_source: Name of the discovery source used for probing.
        per_angle_limit: Cap on results requested per angle probe.
        model: LLM model for the hypothesis stage.
        scout_agent: Optional pre-built agent. If not provided, one is built
            with `model`. Tests pass a pre-built agent so they can
            `agent.override(model=...)` before calling.
        hypothesis_override: For tests: skip the LLM call entirely and feed
            a synthetic hypothesis through the probe stage. When set, the
            agent is not invoked.

    The probe stage swallows per-angle failures (logs + returns the angle
    with no sample evidence). The hypothesis stage's failure propagates.
    """
    if not topic.strip():
        msg = "run_scout: topic must be non-empty"
        raise ValueError(msg)

    if hypothesis_override is not None:
        hypothesis = hypothesis_override
    else:
        agent = scout_agent or make_scout_agent(model)
        result = await agent.run(f"Topic: {topic}")
        hypothesis = result.output

    probe_tasks = [
        _probe_angle(i, h, probe_source, registry, per_angle_limit)
        for i, h in enumerate(hypothesis.angles)
    ]
    probed_angles = await asyncio.gather(*probe_tasks)

    return AngleTree(
        topic=topic,
        angles=list(probed_angles),
        related_fields=hypothesis.related_fields,
        notes=hypothesis.notes,
        scout_model=model,
        probe_source=probe_source,
    )


# ---------- formatting (used by the CLI ceremony) ----------


def render_angle_tree(tree: AngleTree, *, color: bool = False) -> str:
    """Plain-text rendering of an AngleTree for the ceremony's display.

    Color is off by default; the CLI can pass `color=True` and pipe through
    Rich's Console.print for highlighting. Tests use the plain version.
    """
    # We render simple Rich-style markup that's harmless when color=False
    # because the calling layer either invokes Console.print or print().
    style: Literal["plain", "rich"] = "rich" if color else "plain"
    out: list[str] = []
    out.append(f"Topic: {tree.topic}")
    out.append("")
    for i, angle in enumerate(tree.angles, start=1):
        if style == "rich":
            out.append(f"[bold]{i}.[/] [cyan]{angle.name}[/] — {angle.description}")
        else:
            out.append(f"{i}. {angle.name} — {angle.description}")
        if angle.keywords:
            out.append(f"     keywords: {', '.join(angle.keywords)}")
        if angle.hit_count:
            out.append(f"     {angle.hit_count} hits via probe")
        for t in angle.sample_titles[:3]:
            out.append(f"     • {t}")
        out.append("")
    if tree.related_fields:
        out.append("Related fields you might also consider:")
        out.append(f"     {', '.join(tree.related_fields)}")
        out.append("")
    if tree.notes:
        out.append(f"Scout notes: {tree.notes}")
    return "\n".join(out)
