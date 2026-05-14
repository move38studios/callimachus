"""Tests for the build orchestrator.

These exercise the orchestration logic via injected stub hunt/judge/ingest
callables — no real LLMs, no real source plugins, no on-disk pipeline.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlmodel import Session

from callimachus.discovery.hunter import HunterRunResult
from callimachus.discovery.judge import Verdict
from callimachus.discovery.orchestrator import (
    BuildResult,
    _build_query_seeds,  # pyright: ignore[reportPrivateUsage]
    _dedupe,  # pyright: ignore[reportPrivateUsage]
    _filter_resolvable,  # pyright: ignore[reportPrivateUsage]
    run_build,
)
from callimachus.discovery.plan import Angle, AngleTree, Plan
from callimachus.pipeline.enrich import Enrichment
from callimachus.pipeline.ingest import IngestResult
from callimachus.sources.protocols import Provenance, SourceUnavailable, WorkCandidate
from callimachus.storage import Run, Work, init_db, make_engine

# ---------- fixtures ----------


def _candidate(
    *,
    title: str = "T",
    arxiv_id: str | None = "2001.00001",
    source_url: str | None = None,
    abstract: str = "abstract",
) -> WorkCandidate:
    return WorkCandidate(
        title=title,
        source_url=source_url or f"https://arxiv.org/abs/{arxiv_id or 'x'}",
        provenance=Provenance(source_name="stub", query="q"),
        arxiv_id=arxiv_id,
        abstract=abstract,
    )


def _angle(name: str = "angle", description: str = "an angle of some kind") -> Angle:
    return Angle(name=name, description=description, keywords=["kw1", "kw2"])


def _plan(angles: list[Angle] | None = None, **overrides: object) -> Plan:
    if angles is None:
        angles = [_angle("foundations"), _angle("recent")]
    tree = AngleTree(topic=str(overrides.get("topic", "diffusion")), angles=angles)
    base: dict[str, object] = {
        "topic": "diffusion",
        "slug": "diffusion",
        "angles": angles,
        "max_works": 50,
        "discovery": tree,
    }
    base.update(overrides)
    return Plan(**base)  # type: ignore[arg-type]


@pytest.fixture
def session(tmp_path: Path):
    db_path = tmp_path / "lib.db"
    engine = make_engine(f"sqlite:///{db_path}")
    init_db(engine)
    with Session(engine) as s:
        yield s


# ---------- helpers ----------


def test_build_query_seeds_merges_angle_keywords_and_plan_anchors() -> None:
    plan = _plan(extra_keywords=["Hofstadter", "Boden", "kw1"])  # 'kw1' is a dup
    angle = Angle(name="a", description="ok ok ok", keywords=["kw1", "kw2"])
    assert _build_query_seeds(angle, plan) == ["kw1", "kw2", "Hofstadter", "Boden"]


def test_build_query_seeds_falls_back_to_angle_name_when_empty() -> None:
    plan = _plan(extra_keywords=[])
    angle = Angle(name="my-angle", description="ok ok ok", keywords=[])
    assert _build_query_seeds(angle, plan) == ["my-angle"]


def test_filter_resolvable_keeps_arxiv_and_doi_drops_url_only() -> None:
    """With both arxiv and unpaywall resolvers, arxiv_id OR doi suffices."""
    arx = _candidate(arxiv_id="2001.0001")
    doi = WorkCandidate(
        title="doi-only",
        source_url="https://doi.org/10.x/y",
        provenance=Provenance(source_name="openalex", query="q"),
        doi="10.x/y",
    )
    url_only = WorkCandidate(
        title="url-only",
        source_url="https://example.com/post.html",
        provenance=Provenance(source_name="serper_web", query="q"),
    )
    result = _filter_resolvable([arx, doi, url_only], require_resolvable_id=True)
    assert result == [arx, doi]  # both keep, url-only drops


def test_filter_resolvable_passes_through_when_not_required() -> None:
    a, b = _candidate(arxiv_id=None), _candidate(arxiv_id="2001.0001")
    a.arxiv_id = None
    result = _filter_resolvable([a, b], require_resolvable_id=False)
    assert result == [a, b]


def test_dedupe_preserves_input_order_and_drops_duplicates() -> None:
    a = _candidate(arxiv_id="2001.0001")
    b = _candidate(arxiv_id="2001.0002")
    a_dup = _candidate(arxiv_id="2001.0001")  # same candidate_id as a
    assert _dedupe([a, b, a_dup]) == [a, b]


# ---------- run_build (full orchestration) ----------


def _verdict(accept: bool, score: float = 0.8) -> Verdict:
    return Verdict(accept=accept, score=score, reasoning="ok ok ok ok ok ok ok ok ok ok")


async def _stub_hunt(angle: Angle, *, cands: list[WorkCandidate]) -> HunterRunResult:
    return HunterRunResult(
        angle=angle.name,
        candidates=list(cands),
        queries_tried=["q1", "q2"],
        notes="stub hunter notes",
        elapsed_seconds=0.01,
        request_count=3,
        input_tokens=100,
        output_tokens=50,
    )


def _make_stub_judge(verdicts_by_title: dict[str, Verdict]):
    async def stub_judge(topic: str, cand: WorkCandidate) -> Verdict:
        del topic
        return verdicts_by_title.get(cand.title, _verdict(accept=False, score=0.0))

    return stub_judge


def _make_stub_ingest(
    *,
    session: Session,
    fail_titles: set[str] | None = None,
):
    """Stub ingest: persists a real Work row to the session so judge fields can be patched."""
    fail_titles = fail_titles or set()
    calls: list[WorkCandidate] = []

    async def stub_ingest(candidate: WorkCandidate) -> IngestResult:
        if candidate.title in fail_titles:
            raise SourceUnavailable(f"stub: resolver unavailable for {candidate.title!r}")
        calls.append(candidate)
        work_id = f"arxiv-{(candidate.arxiv_id or 'x').replace('.', '-')}"
        work = Work(
            id=work_id,
            kind=candidate.kind,
            title=candidate.title,
            source_url=candidate.source_url,
            arxiv_id=candidate.arxiv_id,
        )
        session.add(work)
        session.flush()
        return IngestResult(
            work_id=work_id,
            work=work,
            enrichment=Enrichment(
                title=candidate.title,
                summary="seminal contribution to the field of stubs and mocks",
            ),
            chunks_indexed=3,
        )

    return stub_ingest, calls


async def test_run_build_happy_path_writes_run_and_patches_work_rows(
    session: Session,
) -> None:
    a1 = _candidate(title="A", arxiv_id="2001.0001")
    a2 = _candidate(title="B", arxiv_id="2001.0002")  # accepted
    a3 = _candidate(title="C", arxiv_id="2001.0003")  # rejected by judge

    async def hunt(angle: Angle) -> HunterRunResult:
        return await _stub_hunt(angle, cands=[a1, a2, a3])

    judge = _make_stub_judge(
        {
            "A": _verdict(accept=True, score=0.9),
            "B": _verdict(accept=True, score=0.7),
            "C": _verdict(accept=False, score=0.1),
        }
    )
    ingest, ingest_calls = _make_stub_ingest(session=session)

    # Pre-create the Work rows that ingest will return so patching can succeed
    plan = _plan()
    result = await run_build(
        plan=plan,
        session=session,
        judge_fn=judge,
        hunt_fn=hunt,
        ingest_fn=ingest,
    )
    session.commit()

    assert isinstance(result, BuildResult)
    assert result.candidates_total == 2 * 3  # 2 angles x 3 cands each
    assert result.candidates_after_filter == 3  # dedup -> 3
    assert result.candidates_judged == 3
    assert result.candidates_accepted == 2
    assert result.works_added == 2
    assert result.errors == []
    assert {c.title for c in ingest_calls} == {"A", "B"}

    # Run row written
    run = session.get(Run, result.run_id)
    assert run is not None
    assert run.kind == "build"
    assert run.works_added == 2
    assert run.ended_at is not None
    notes = json.loads(run.notes or "{}")
    assert notes["candidates_accepted"] == 2
    assert notes["hunter_token_totals"]["input_tokens"] >= 100

    # Work rows patched with judge fields + admitted_by_run_id
    work_a = session.get(Work, "arxiv-2001-0001")
    work_b = session.get(Work, "arxiv-2001-0002")
    assert work_a is not None and work_b is not None
    assert work_a.judge_score == 0.9
    assert work_b.judge_score == 0.7
    assert work_a.admitted_by_run_id == result.run_id
    assert work_b.admitted_by_run_id == result.run_id
    # 'C' should not have been ingested
    assert session.get(Work, "arxiv-2001-0003") is None


async def test_run_build_filters_unresolvable_before_judging(session: Session) -> None:
    """Candidates without an arxiv_id OR doi must be dropped before the judge sees them.

    DOI-only candidates are kept now that Unpaywall is in the resolver chain.
    """
    arx = _candidate(title="A", arxiv_id="2001.0001")
    doi_only = WorkCandidate(
        title="DOI-only",
        source_url="https://doi.org/10.x/y",
        provenance=Provenance(source_name="openalex", query="q"),
        doi="10.x/y",
    )
    url_only = WorkCandidate(
        title="URL-only",
        source_url="https://example.com/blog-post",
        provenance=Provenance(source_name="serper_web", query="q"),
    )
    judge_seen: list[str] = []

    async def hunt(angle: Angle) -> HunterRunResult:
        return await _stub_hunt(angle, cands=[arx, doi_only, url_only])

    async def judge(topic: str, cand: WorkCandidate) -> Verdict:
        del topic
        judge_seen.append(cand.title)
        return _verdict(accept=False)  # don't ingest, just verify filter

    ingest, _ = _make_stub_ingest(session=session)

    result = await run_build(
        plan=_plan(angles=[_angle("one")]),
        session=session,
        judge_fn=judge,
        hunt_fn=hunt,
        ingest_fn=ingest,
    )
    session.commit()
    assert sorted(judge_seen) == ["A", "DOI-only"]  # url-only was filtered out
    assert result.candidates_after_filter == 2


async def test_run_build_caps_at_plan_max_works(session: Session) -> None:
    """When more candidates are accepted than max_works, take the top-scored."""
    cands = [_candidate(title=str(i), arxiv_id=f"2001.000{i}") for i in range(5)]

    async def hunt(angle: Angle) -> HunterRunResult:
        return await _stub_hunt(angle, cands=cands)

    # Decreasing scores so we can confirm ordering
    scores = {
        "0": 0.95,
        "1": 0.85,
        "2": 0.75,
        "3": 0.65,
        "4": 0.55,
    }

    async def judge(topic: str, cand: WorkCandidate) -> Verdict:
        del topic
        return _verdict(accept=True, score=scores[cand.title])

    ingest, ingest_calls = _make_stub_ingest(session=session)
    plan = _plan(angles=[_angle("one")], max_works=3)

    result = await run_build(
        plan=plan,
        session=session,
        judge_fn=judge,
        hunt_fn=hunt,
        ingest_fn=ingest,
    )
    session.commit()
    assert result.candidates_accepted == 3
    assert result.works_added == 3
    titles_ingested = sorted(c.title for c in ingest_calls)
    assert titles_ingested == ["0", "1", "2"]  # top 3 by score


async def test_run_build_records_ingest_failures_in_errors(session: Session) -> None:
    arx = _candidate(title="A", arxiv_id="2001.0001")

    async def hunt(angle: Angle) -> HunterRunResult:
        return await _stub_hunt(angle, cands=[arx])

    judge = _make_stub_judge({"A": _verdict(accept=True)})
    ingest, _ = _make_stub_ingest(session=session, fail_titles={"A"})

    result = await run_build(
        plan=_plan(angles=[_angle("one")]),
        session=session,
        judge_fn=judge,
        hunt_fn=hunt,
        ingest_fn=ingest,
    )
    session.commit()
    assert result.candidates_accepted == 1
    assert result.works_added == 0
    assert any("ingest" in e for e in result.errors)
    # Judged record retains the verdict even though ingest failed
    assert result.judged[0].ingested is False
    assert "resolver unavailable" in (result.judged[0].ingest_error or "")


async def test_run_build_records_hunter_failures_in_errors(session: Session) -> None:
    """A hunter raising should not crash the build — it goes in errors list."""

    async def bad_hunt(angle: Angle) -> HunterRunResult:
        raise SourceUnavailable(f"hunter {angle.name!r} broken")

    async def judge(topic: str, cand: WorkCandidate) -> Verdict:
        del topic, cand
        return _verdict(accept=True)

    ingest, _ = _make_stub_ingest(session=session)

    result = await run_build(
        plan=_plan(angles=[_angle("one"), _angle("two")]),
        session=session,
        judge_fn=judge,
        hunt_fn=bad_hunt,
        ingest_fn=ingest,
    )
    session.commit()
    assert result.candidates_total == 0
    assert len(result.errors) == 2
    assert result.works_added == 0


async def test_run_build_run_row_kind_and_config(session: Session) -> None:
    """The Run row must carry kind='build' and the plan config in JSON."""

    async def hunt(angle: Angle) -> HunterRunResult:
        return await _stub_hunt(angle, cands=[])

    async def judge(topic: str, cand: WorkCandidate) -> Verdict:
        del topic, cand
        return _verdict(accept=False)

    ingest, _ = _make_stub_ingest(session=session)
    plan = _plan(angles=[_angle("a")], orientation="foundations", max_works=10)
    result = await run_build(
        plan=plan,
        session=session,
        judge_fn=judge,
        hunt_fn=hunt,
        ingest_fn=ingest,
    )
    session.commit()
    run = session.get(Run, result.run_id)
    assert run is not None
    assert run.kind == "build"
    assert run.config["topic"] == "diffusion"
    assert run.config["orientation"] == "foundations"
    assert run.config["max_works"] == 10
    assert run.config["require_resolvable_id"] is True
