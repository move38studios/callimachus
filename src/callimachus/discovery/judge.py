"""Judge — single LLM call: accept or reject a WorkCandidate for a topic.

Sits between discovery and ingest: the hunter agent collects candidates,
the judge decides which ones earn a download + extract + embed cycle.

Same shape as `pipeline.enrich`: a `Verdict` schema + a stub-friendly
`JudgeFn = Callable[[str, WorkCandidate], Awaitable[Verdict]]`. Tests pass
a stub; production wires `make_default_judge()` which builds a Pydantic AI
agent under the hood.

We auto-reject obviously-bad candidates (no title, no source URL) before
the LLM is called — cheap shortcut, also keeps the agent honest about what
"accept" means.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from pydantic import BaseModel, Field

from callimachus.llm import MODEL_SMART
from callimachus.sources.protocols import WorkCandidate

# Some candidate data is large (e.g. paper abstracts up to ~3k chars).
# Cap to keep judge prompts predictable; judges shouldn't need more.
MAX_ABSTRACT_CHARS = 3000


class Verdict(BaseModel):
    """The judge's decision on one candidate."""

    accept: bool = Field(
        description="True if this work belongs in the library for the given topic."
    )
    score: float = Field(
        ge=0.0,
        le=1.0,
        description=(
            "Relevance confidence. 0.0 = clearly off-topic, 1.0 = clearly central. "
            "Threshold is around 0.4: above it usually means accept."
        ),
    )
    reasoning: str = Field(
        min_length=10,
        description="One or two sentences explaining the decision. No hedging.",
    )
    notes: str | None = Field(
        default=None,
        description=(
            "Optional flag for data-quality concerns "
            "(e.g. 'title and abstract appear to be from different papers'). "
            "Leave null if nothing is amiss."
        ),
    )


JudgeFn = Callable[[str, WorkCandidate], Awaitable[Verdict]]


JUDGE_SYSTEM_PROMPT = """\
You are a research librarian deciding whether a candidate work belongs in a
library on a specific topic.

You will receive the topic and a candidate's metadata (title, authors, year,
venue, abstract, source). Decide: does this work plausibly contribute to a
deep library on this topic?

Rules:
- Be pragmatic. Borderline relevance is fine; only reject works that are
  clearly off-topic or obviously low-signal (link bait, marketing pages,
  Q&A threads).
- A foundational paper that predates the modern framing of the topic is
  accepted with a high score — older does not mean less relevant.
- Surveys and review articles count.
- If the metadata looks inconsistent (e.g. title and abstract appear to be
  from different works), accept if the title plausibly fits the topic but
  set `notes` so downstream code can flag it.
- `score` is your own confidence, not a popularity vote. Don't anchor on
  citation counts unless they're the only relevance signal you have.
- Keep `reasoning` to one or two sentences. State the actual reason; don't
  describe what the paper does.
"""


def _candidate_summary(candidate: WorkCandidate) -> str:
    """Render the candidate as a compact human-readable block for the judge."""
    lines = [f"Title: {candidate.title}"]
    if candidate.authors:
        lines.append(f"Authors: {', '.join(candidate.authors[:8])}")
    if candidate.year is not None:
        lines.append(f"Year: {candidate.year}")
    if candidate.venue:
        lines.append(f"Venue: {candidate.venue}")
    lines.append(f"Source: {candidate.source_url}")
    lines.append(f"Origin plugin: {candidate.provenance.source_name}")
    if candidate.kind != "paper":
        lines.append(f"Kind: {candidate.kind}")
    cited = candidate.extras.get("cited_by_count")
    if cited is not None:
        lines.append(f"Cited by: {cited}")
    if candidate.abstract:
        abstract = candidate.abstract.strip()
        if len(abstract) > MAX_ABSTRACT_CHARS:
            abstract = abstract[:MAX_ABSTRACT_CHARS] + "…"
        lines.append("")
        lines.append("Abstract:")
        lines.append(abstract)
    return "\n".join(lines)


def render_judge_prompt(topic: str, candidate: WorkCandidate) -> str:
    """The user-side prompt content. Public so callers / tests can inspect it."""
    return f"Topic: {topic}\n\nCandidate:\n{_candidate_summary(candidate)}"


# ---------- the stage ----------


def _auto_reject_reason(candidate: WorkCandidate) -> str | None:
    """Cheap pre-LLM rejection. Returns a reason string or None."""
    if not candidate.title.strip():
        return "missing title"
    if not candidate.source_url.strip():
        return "missing source URL"
    return None


async def judge_candidate(
    topic: str,
    candidate: WorkCandidate,
    *,
    judge_fn: JudgeFn,
) -> Verdict:
    """Score one candidate against a topic.

    Auto-rejects candidates with no title or no URL without calling the LLM.
    Otherwise hands off to `judge_fn` (LLM or stub).
    """
    if not topic.strip():
        msg = "judge_candidate: topic must be non-empty"
        raise ValueError(msg)

    if (reason := _auto_reject_reason(candidate)) is not None:
        return Verdict(
            accept=False,
            score=0.0,
            reasoning=f"Auto-rejected: {reason}.",
            notes=None,
        )

    return await judge_fn(topic, candidate)


# ---------- default Pydantic AI judge ----------


def make_default_judge(model: str = MODEL_SMART) -> JudgeFn:
    """Build the default Pydantic AI-backed judge.

    Lazy-imports `pydantic_ai` so callers using a stub judge (tests, dry-runs)
    don't pay the import cost.
    """
    from pydantic_ai import Agent

    agent: Agent[None, Verdict] = Agent(
        model,
        output_type=Verdict,
        system_prompt=JUDGE_SYSTEM_PROMPT,
    )

    async def _judge(topic: str, candidate: WorkCandidate) -> Verdict:
        prompt = render_judge_prompt(topic, candidate)
        result = await agent.run(prompt)
        return result.output

    return _judge
