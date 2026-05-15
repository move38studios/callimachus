"""Orchestrator — drives a Plan to indexed library.

Sequence:

    plan
      → hunt(angle)  xN parallel  -> list[WorkCandidate]
      -> dedupe by candidate_id
      -> filter (require_resolvable_id: arxiv_id or doi)
      -> judge xN (concurrency-capped)
      -> ingest accepted   ->  Work rows
      -> patch judge_score + judge_reasoning + admitted_by_run_id on each Work
      -> finalise Run row

The orchestrator takes the heavy callables (`hunt_fn`, `judge_fn`,
`ingest_fn`) as parameters so tests can inject stubs without standing up a
real LLM, source plugin chain, or pipeline. The CLI in M2.5 will wire the
real implementations.

Token totals are written to the Run's `notes` JSON. No USD math — per
project decision (DEV_PLAN.md M1.5 cancellation).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlmodel import Session

from callimachus.discovery.hunter import (
    DEFAULT_REQUEST_LIMIT as HUNTER_REQUEST_LIMIT,
)
from callimachus.discovery.hunter import (
    HunterRunResult,
    run_hunter,
)
from callimachus.discovery.judge import JudgeFn, Verdict, judge_candidate
from callimachus.discovery.plan import Angle, Plan
from callimachus.llm import MODEL_SMART
from callimachus.pipeline.embed import Embedder
from callimachus.pipeline.enrich import EnrichFn
from callimachus.pipeline.ingest import IngestResult, ingest_one
from callimachus.pipeline.ocr.protocols import OcrProvider
from callimachus.sources.protocols import SourceUnavailable, WorkCandidate
from callimachus.sources.registry import SourceRegistry
from callimachus.storage import Run, Work

log = logging.getLogger(__name__)

# Concurrency defaults — bounded to avoid pummelling LLM rate limits.
DEFAULT_JUDGE_CONCURRENCY = 5

# When ingest fails for a candidate, we keep trying down the score-ranked
# accepted list until we hit plan.max_works successes — but with a cap
# so a high-failure-rate run doesn't go forever. Default cap = 2x
# max_works (so for max_works=15 we attempt at most 30 candidates).
DEFAULT_MAX_ATTEMPTS_MULTIPLIER = 2

HuntFn = Callable[[Angle], Awaitable[HunterRunResult]]
IngestFn = Callable[[WorkCandidate], Awaitable[IngestResult]]


@dataclass(slots=True)
class JudgedCandidate:
    """One judged candidate with its verdict and ingest outcome."""

    candidate: WorkCandidate
    verdict: Verdict
    ingested: bool = False
    ingest_error: str | None = None
    work_id: str | None = None


@dataclass(slots=True)
class BuildResult:
    """Summary returned by `run_build`."""

    run_id: int
    plan: Plan
    candidates_total: int
    candidates_after_filter: int
    candidates_judged: int
    judge_accepted: int  # how many the judge said yes to (full pool, no cap)
    candidates_attempted: int  # how many we tried to ingest (until max_works successes or cap)
    works_added: int  # successful ingests
    hunter_results: list[HunterRunResult]
    judged: list[JudgedCandidate]
    elapsed_seconds: float
    errors: list[str]


# ---------- helpers ----------


def _build_query_seeds(angle: Angle, plan: Plan) -> list[str]:
    """Combine the angle's keywords with the user's plan-level anchors."""
    seeds: list[str] = list(angle.keywords)
    for kw in plan.extra_keywords:
        if kw not in seeds:
            seeds.append(kw)
    return seeds or [angle.name]


def _angle_brief(angle: Angle, plan: Plan) -> str:
    """Human-readable label combining angle name + description + orientation hint."""
    parts = [f"{angle.name}: {angle.description}"]
    if plan.orientation == "foundations":
        parts.append("Bias toward seminal / foundational works.")
    elif plan.orientation == "recent":
        parts.append("Bias toward recent (last ~3 years) state-of-the-art.")
    return " — ".join(parts)


def _filter_resolvable(
    candidates: list[WorkCandidate], *, require_resolvable_id: bool
) -> list[WorkCandidate]:
    """Drop candidates the resolver chain can't fetch.

    With arxiv (handles arxiv_id) and unpaywall (handles doi) both in the
    registry, a candidate is resolvable if it has EITHER an arxiv_id or a
    doi. We filter them out *before* judging to save LLM tokens.

    Pass `require_resolvable_id=False` to skip the filter entirely — useful
    for tests or for users who've installed third-party resolvers that
    handle other identifiers.
    """
    if not require_resolvable_id:
        return candidates
    return [c for c in candidates if c.arxiv_id or c.doi]


def _dedupe(candidates: list[WorkCandidate]) -> list[WorkCandidate]:
    """Preserve input order, drop duplicates by `candidate_id`."""
    seen: set[str] = set()
    out: list[WorkCandidate] = []
    for c in candidates:
        if c.candidate_id in seen:
            continue
        seen.add(c.candidate_id)
        out.append(c)
    return out


def _summarise_hunter_tokens(hunter_results: list[HunterRunResult]) -> dict[str, int]:
    """Sum input/output tokens + request counts across hunters."""
    input_tokens = sum(h.input_tokens or 0 for h in hunter_results)
    output_tokens = sum(h.output_tokens or 0 for h in hunter_results)
    request_count = sum(h.request_count or 0 for h in hunter_results)
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "request_count": request_count,
    }


# ---------- hunt / judge / admit stages ----------


def make_hunt_fn(
    *,
    plan: Plan,
    registry: SourceRegistry,
    hunter_model: str = MODEL_SMART,
    request_limit: int = HUNTER_REQUEST_LIMIT,
    source_names: list[str] | None = None,
) -> HuntFn:
    """Build the default HuntFn for `run_build`. Closes over plan + registry.

    `source_names` overrides `plan.source_names` when set. Use this to
    restrict the hunter to a subset of registered sources — typically
    bibliographic-only when require_resolvable_id-style filtering would
    discard the rest anyway, so the agent doesn't burn tokens calling tools
    whose output we silently drop.
    """
    effective_sources = source_names if source_names is not None else plan.source_names

    async def _hunt(angle: Angle) -> HunterRunResult:
        return await run_hunter(
            topic=plan.topic,
            angle=_angle_brief(angle, plan),
            query_seeds=_build_query_seeds(angle, plan),
            registry=registry,
            year_from=plan.year_from,
            year_to=plan.year_to,
            kinds=plan.kinds,
            source_names=effective_sources,
            model=hunter_model,
            request_limit=request_limit,
        )

    return _hunt


def make_ingest_fn(
    *,
    library_root: Path,
    session: Session,
    registry: SourceRegistry,
    enricher: EnrichFn,
    embedder: Embedder,
    ocr: OcrProvider | None = None,
) -> IngestFn:
    """Build the default IngestFn for `run_build`. Closes over pipeline deps."""

    async def _ingest(candidate: WorkCandidate) -> IngestResult:
        return await ingest_one(
            candidate,
            library_root=library_root,
            session=session,
            registry=registry,
            enricher=enricher,
            embedder=embedder,
            ocr=ocr,
        )

    return _ingest


async def _judge_one(
    candidate: WorkCandidate,
    plan: Plan,
    *,
    judge_fn: JudgeFn,
    semaphore: asyncio.Semaphore,
) -> tuple[WorkCandidate, Verdict | Exception]:
    """Judge one candidate behind the concurrency semaphore."""
    async with semaphore:
        try:
            verdict = await judge_candidate(plan.topic, candidate, judge_fn=judge_fn)
        except Exception as exc:
            log.warning(
                "orchestrator: judge failed for %r: %s: %s",
                candidate.candidate_id,
                type(exc).__name__,
                exc,
            )
            return candidate, exc
        return candidate, verdict


# ---------- main entry point ----------


async def run_build(
    *,
    plan: Plan,
    session: Session,
    judge_fn: JudgeFn,
    hunt_fn: HuntFn,
    ingest_fn: IngestFn,
    require_resolvable_id: bool = True,
    judge_concurrency: int = DEFAULT_JUDGE_CONCURRENCY,
    max_attempts_multiplier: int = DEFAULT_MAX_ATTEMPTS_MULTIPLIER,
) -> BuildResult:
    """Execute a build Plan end-to-end.

    Args:
        plan: The Plan to execute (from M2.3 ceremony).
        session: SQLModel session bound to the library DB. We create + update
            the `Run` row and patch `Work` rows after ingest.
        judge_fn: Per-candidate judge (M2.1).
        hunt_fn: Per-angle hunter callable. See `make_hunt_fn` for the
            default that wires up `run_hunter`.
        ingest_fn: Per-candidate ingest callable. See `make_ingest_fn` for
            the default that wires up `ingest_one`.
        require_resolvable_id: If True (default), filter candidates that
            don't have an arxiv_id OR a doi before judging — the bundled
            resolver chain (arxiv + unpaywall) needs one of those to fetch
            the artifact. Disable when third-party resolvers handle other
            identifiers.
        judge_concurrency: Max parallel judge calls.
        max_attempts_multiplier: Bound the ingest attempt count at
            `max(plan.max_works * multiplier, plan.max_works + 5)`. Lets
            the orchestrator try further down the judge-accepted list when
            high-scored picks fail at the resolver (publisher 403s, etc.).
            Set to 1 to restore the strict cap behaviour.

    Returns a `BuildResult` summarising what was attempted, judged, accepted,
    and ingested. The `Run` row is persisted on the session before this
    returns; the caller is responsible for `session.commit()` if they want
    the changes durable on disk.
    """
    started = time.perf_counter()
    started_at = datetime.now(UTC)

    # 1. Create the Run row early so per-ingest work can reference it
    run = Run(
        kind="build",
        started_at=started_at,
        config={
            "topic": plan.topic,
            "slug": plan.slug,
            "angle_count": len(plan.angles),
            "orientation": plan.orientation,
            "max_works": plan.max_works,
            "require_resolvable_id": require_resolvable_id,
        },
    )
    session.add(run)
    session.flush()
    if run.id is None:
        msg = "orchestrator: Run.id not assigned after flush — DB schema issue?"
        raise RuntimeError(msg)
    run_id = run.id
    log.info("build run %d started — topic=%r, %d angles", run_id, plan.topic, len(plan.angles))

    errors: list[str] = []

    # 2. Fan out hunters in parallel (we control concurrency, not the model).
    # Wrap each hunt call so completion logs interleave as they finish, instead
    # of a single line after asyncio.gather returns.
    async def _hunt_with_log(angle: Angle) -> HunterRunResult:
        log.info("build run %d: hunter starting — angle=%r", run_id, angle.name)
        result = await hunt_fn(angle)
        log.info(
            "build run %d: hunter done — angle=%r, %d candidates, %.1fs, %d req",
            run_id,
            angle.name,
            len(result.candidates),
            result.elapsed_seconds,
            result.request_count or 0,
        )
        return result

    hunter_results: list[HunterRunResult] = []
    hunter_tasks = [_hunt_with_log(angle) for angle in plan.angles]
    raw = await asyncio.gather(*hunter_tasks, return_exceptions=True)
    for angle, outcome in zip(plan.angles, raw, strict=True):
        if isinstance(outcome, BaseException):
            msg = f"hunter for angle {angle.name!r} failed: {type(outcome).__name__}: {outcome}"
            log.warning("orchestrator: %s", msg)
            errors.append(msg)
        else:
            hunter_results.append(outcome)

    # 3. Aggregate + dedupe candidates across hunters
    all_candidates: list[WorkCandidate] = []
    for hr in hunter_results:
        all_candidates.extend(hr.candidates)
    unique = _dedupe(all_candidates)
    log.info(
        "build run %d: gathered %d candidates (%d unique after dedup)",
        run_id,
        len(all_candidates),
        len(unique),
    )

    # 4. Filter to those the resolver chain can fetch
    filtered = _filter_resolvable(unique, require_resolvable_id=require_resolvable_id)
    log.info(
        "build run %d: %d candidates remain after require_resolvable_id=%s filter",
        run_id,
        len(filtered),
        require_resolvable_id,
    )

    # 5. Judge — concurrency-capped, in input (rank) order
    semaphore = asyncio.Semaphore(judge_concurrency)
    judge_tasks = [_judge_one(c, plan, judge_fn=judge_fn, semaphore=semaphore) for c in filtered]
    judge_outcomes = await asyncio.gather(*judge_tasks)

    judged: list[JudgedCandidate] = []
    for cand, outcome in judge_outcomes:
        if isinstance(outcome, Exception):
            errors.append(
                f"judge failed for {cand.candidate_id}: {type(outcome).__name__}: {outcome}"
            )
            judged.append(
                JudgedCandidate(
                    candidate=cand,
                    verdict=Verdict(
                        accept=False,
                        score=0.0,
                        reasoning=f"Judge raised: {type(outcome).__name__}",
                    ),
                )
            )
        else:
            judged.append(JudgedCandidate(candidate=cand, verdict=outcome))

    accepted_all = [j for j in judged if j.verdict.accept]
    # Sort accepted by score descending so the highest-confidence picks try first
    accepted_all.sort(key=lambda j: j.verdict.score, reverse=True)
    judge_accepted_total = len(accepted_all)

    # 6. Ingest — keep going down the judge-accepted list until we hit
    # plan.max_works successes OR the attempt cap. This lets us recover
    # from the long tail of publisher-blocked DOIs without leaving
    # accepted-but-untried candidates on the table.
    target_successes = plan.max_works
    max_attempts = max(target_successes * max_attempts_multiplier, target_successes + 5)
    max_attempts = min(max_attempts, judge_accepted_total)

    if judge_accepted_total > target_successes:
        log.info(
            "build run %d: judge accepted %d; will try up to %d to fill %d slots",
            run_id,
            judge_accepted_total,
            max_attempts,
            target_successes,
        )

    works_added = 0
    attempted_count = 0
    for j in accepted_all[:max_attempts]:
        if works_added >= target_successes:
            break
        attempted_count += 1
        label = j.candidate.title[:80] if j.candidate.title else j.candidate.candidate_id
        log.info(
            "build run %d: [%d/%d] ingesting (score=%.2f) %s",
            run_id,
            works_added + 1,  # display the slot we're trying to fill
            target_successes,
            j.verdict.score,
            label,
        )
        try:
            result = await ingest_fn(j.candidate)
        except SourceUnavailable as exc:
            j.ingest_error = f"resolver unavailable: {exc}"
            errors.append(f"ingest {j.candidate.candidate_id}: {j.ingest_error}")
            log.warning(
                "build run %d: ✗ resolver unavailable for %r: %s",
                run_id,
                j.candidate.candidate_id,
                exc,
            )
            continue
        except Exception as exc:
            j.ingest_error = f"{type(exc).__name__}: {exc}"
            errors.append(f"ingest {j.candidate.candidate_id}: {j.ingest_error}")
            log.exception(
                "build run %d: ✗ ingest %r unexpected failure",
                run_id,
                j.candidate.candidate_id,
            )
            continue

        j.ingested = True
        j.work_id = result.work_id
        works_added += 1
        log.info(
            "build run %d: [%d/%d] ✓ %s (%d chunks)",
            run_id,
            works_added,
            target_successes,
            result.work_id,
            result.chunks_indexed,
        )

        # Patch the Work row with judge fields + run linkage
        work_row = session.get(Work, result.work_id)
        if work_row is not None:
            work_row.judge_score = j.verdict.score
            work_row.judge_reasoning = j.verdict.reasoning
            work_row.admitted_by_run_id = run_id
            session.flush()
        else:
            log.warning(
                "orchestrator: Work %r missing after ingest_one — judge fields not set",
                result.work_id,
            )

    if works_added < target_successes and attempted_count >= max_attempts:
        log.warning(
            "build run %d: hit attempt cap (%d) before filling %d slots — only %d added",
            run_id,
            max_attempts,
            target_successes,
            works_added,
        )

    # 7. Finalise the Run row
    elapsed = time.perf_counter() - started
    notes_blob: dict[str, object] = {
        "hunter_token_totals": _summarise_hunter_tokens(hunter_results),
        "judge_concurrency": judge_concurrency,
        "candidates_total": len(all_candidates),
        "candidates_unique": len(unique),
        "candidates_after_filter": len(filtered),
        "candidates_judged": len(judged),
        "judge_accepted": judge_accepted_total,
        "candidates_attempted": attempted_count,
        "max_attempts_cap": max_attempts,
        "errors": errors,
    }
    run.ended_at = datetime.now(UTC)
    run.works_added = works_added
    run.notes = json.dumps(notes_blob, sort_keys=True)
    session.flush()

    log.info(
        "build run %d finished in %.1fs — %d works added (%d errors)",
        run_id,
        elapsed,
        works_added,
        len(errors),
    )

    return BuildResult(
        run_id=run_id,
        plan=plan,
        candidates_total=len(all_candidates),
        candidates_after_filter=len(filtered),
        candidates_judged=len(judged),
        judge_accepted=judge_accepted_total,
        candidates_attempted=attempted_count,
        works_added=works_added,
        hunter_results=hunter_results,
        judged=judged,
        elapsed_seconds=elapsed,
        errors=errors,
    )
