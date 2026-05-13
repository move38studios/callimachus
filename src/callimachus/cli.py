"""Callimachus CLI — `calli init`, `calli ingest`, `calli query`, `calli build`.

Async commands are wrapped with `asyncio.run`. Library root resolves
from the explicit `--library` flag → `$CALLIMACHUS_LIBRARY` → `~/Callimachus`.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Iterable
from pathlib import Path
from typing import Annotated, Any, cast

import typer
import yaml
from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel
from rich.table import Table

from callimachus.discovery.ceremony import CliPrompter, run_ceremony
from callimachus.discovery.judge import make_default_judge
from callimachus.discovery.orchestrator import (
    BuildResult,
    make_hunt_fn,
    make_ingest_fn,
    run_build,
)
from callimachus.discovery.plan import Plan, load_plan, save_plan
from callimachus.discovery.scout import run_scout
from callimachus.pipeline.embed import (
    Embedder,
    NomicEmbedder,
)
from callimachus.pipeline.enrich import EnrichFn, make_default_enricher
from callimachus.pipeline.ingest import ingest_one
from callimachus.pipeline.ocr import MistralOcr
from callimachus.pipeline.ocr.protocols import OcrProvider
from callimachus.pipeline.paths import get_library_root
from callimachus.sources import (
    Provenance,
    SourceRegistry,
    WorkCandidate,
    default_registry,
)
from callimachus.storage import (
    Work,
    init_db,
    make_engine,
    make_session,
    search_chunks,
)

console = Console()
err_console = Console(stderr=True)

app = typer.Typer(
    name="calli",
    help="Callimachus — your personal librarian.",
    no_args_is_help=True,
    add_completion=False,
)


def _load_env_file(path: Path) -> None:
    """First-wins loader: don't overwrite vars already set in the environment."""
    if not path.is_file():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and value and key not in os.environ:
            os.environ[key] = value


def _bootstrap_env(library_root: Path | None = None) -> None:
    """Load `.env` from the library root + the cwd if present.

    Existing environment variables win (first-wins). Quiet — never errors
    on missing files. Intended to be called at the top of every command.
    """
    if library_root is not None:
        _load_env_file(library_root / ".env")
    _load_env_file(Path.cwd() / ".env")


def _setup_logging(verbose: bool) -> None:
    """Wire stdlib logging through Rich so library debug surfaces nicely."""
    level = logging.DEBUG if verbose else logging.INFO
    handler = RichHandler(
        console=err_console,
        rich_tracebacks=True,
        markup=True,
        show_path=False,
        omit_repeated_times=False,
    )
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    root.setLevel(level)
    root.addHandler(handler)
    if not verbose:
        for noisy in ("httpx", "httpcore", "openai", "anthropic"):
            logging.getLogger(noisy).setLevel(logging.WARNING)


def _resolve_library(override: Path | None) -> Path:
    """Resolve the library root and ensure the parent dir exists."""
    return get_library_root(override).expanduser().resolve()


def _candidate_from_yaml_entry(entry: dict[str, Any], *, source: str) -> WorkCandidate:
    """Build a WorkCandidate from one YAML seed entry.

    Supported shapes:
        {"arxiv": "2006.11239"}
        {"doi": "10.1234/foo"}
        {"url": "https://example.org/paper.pdf"}
        {"title": "...", "source_url": "...", "authors": [...], ...}
    """
    if "arxiv" in entry:
        arxiv_id = str(entry["arxiv"])
        return WorkCandidate(
            title=entry.get("title") or f"arxiv:{arxiv_id}",
            source_url=f"https://arxiv.org/abs/{arxiv_id}",
            provenance=Provenance(source_name=source, query=arxiv_id),
            arxiv_id=arxiv_id,
            kind="paper",
        )
    if "doi" in entry:
        doi = str(entry["doi"])
        return WorkCandidate(
            title=entry.get("title") or f"doi:{doi}",
            source_url=entry.get("source_url") or f"https://doi.org/{doi}",
            provenance=Provenance(source_name=source, query=doi),
            doi=doi,
            kind="paper",
        )
    if "url" in entry:
        url = str(entry["url"])
        return WorkCandidate(
            title=entry.get("title") or url,
            source_url=url,
            provenance=Provenance(source_name=source, query=url),
            kind="paper",
        )
    # Custom fully-specified candidate
    if "title" not in entry or "source_url" not in entry:
        msg = (
            f"seed entry must include one of: arxiv, doi, url; OR title + source_url. "
            f"Got: {sorted(entry.keys())!r}"
        )
        raise ValueError(msg)
    return WorkCandidate(
        title=entry["title"],
        source_url=entry["source_url"],
        provenance=Provenance(source_name=source, query=entry["title"]),
        doi=entry.get("doi"),
        arxiv_id=entry.get("arxiv_id"),
        authors=entry.get("authors", []),
        year=entry.get("year"),
        venue=entry.get("venue"),
        kind=entry.get("kind", "paper"),
    )


def _load_seed_file(path: Path) -> list[WorkCandidate]:
    """Parse a seed.yaml into a list of WorkCandidates."""
    raw_obj: object = yaml.safe_load(path.read_text())
    if not isinstance(raw_obj, list):
        msg = f"seed file {path} must be a YAML list; got {type(raw_obj).__name__}"
        raise ValueError(msg)
    raw = cast("list[Any]", raw_obj)
    candidates: list[WorkCandidate] = []
    for i, entry in enumerate(raw):
        if not isinstance(entry, dict):
            msg = f"seed file entry #{i} must be a mapping; got {type(entry).__name__}"
            raise ValueError(msg)
        entry_dict = cast("dict[str, Any]", entry)
        candidates.append(_candidate_from_yaml_entry(entry_dict, source=f"seed:{path.name}"))
    return candidates


# ---------- init ----------


@app.command("init")
def init_cmd(
    path: Annotated[
        Path | None,
        typer.Argument(
            help="Library path. Defaults to ~/Callimachus or $CALLIMACHUS_LIBRARY.",
        ),
    ] = None,
) -> None:
    """Create a new Callimachus library directory."""
    library_root = _resolve_library(path)
    library_root.mkdir(parents=True, exist_ok=True)

    for sub in ("works", "collections", "archive", "plugins", ".callimachus"):
        (library_root / sub).mkdir(exist_ok=True)

    db_path = library_root / "library.db"
    engine = make_engine(f"sqlite:///{db_path}")
    init_db(engine)

    console.print(
        Panel.fit(
            f"[bold green]✓ library ready[/]\n[dim]{library_root}[/]",
            title="calli init",
        )
    )


# ---------- ingest ----------


async def _run_ingest(
    candidates: Iterable[WorkCandidate],
    *,
    library_root: Path,
    fail_fast: bool,
    enricher: EnrichFn,
    embedder: Embedder,
    ocr: OcrProvider | None,
    registry: SourceRegistry,
) -> tuple[int, int]:
    """Run ingest_one over each candidate. Returns (succeeded, failed)."""
    db_path = library_root / "library.db"
    engine = make_engine(f"sqlite:///{db_path}")

    succeeded = 0
    failed = 0
    candidates = list(candidates)
    total = len(candidates)

    for i, candidate in enumerate(candidates, start=1):
        label = candidate.arxiv_id or candidate.doi or candidate.source_url
        console.print(f"[dim]{i}/{total}[/] [bold]ingesting[/] {label}")
        try:
            with make_session(engine) as session:
                result = await ingest_one(
                    candidate,
                    library_root=library_root,
                    session=session,
                    registry=registry,
                    enricher=enricher,
                    embedder=embedder,
                    ocr=ocr,
                )
            console.print(
                f"  [green]✓[/] [bold]{result.work.title}[/]  "
                f"[dim]{result.chunks_indexed} chunks[/]"
            )
            succeeded += 1
        except Exception as exc:
            failed += 1
            err_console.print(f"  [red]✗ {type(exc).__name__}:[/] {exc}")
            if fail_fast:
                raise

    return succeeded, failed


@app.command("ingest")
def ingest_cmd(
    seed: Annotated[Path, typer.Argument(help="Path to a seed YAML file.")],
    library: Annotated[
        Path | None,
        typer.Option("--library", "-L", help="Library root (default: ~/Callimachus)."),
    ] = None,
    fail_fast: Annotated[
        bool,
        typer.Option("--fail-fast", help="Abort on first error (default: log + continue)."),
    ] = False,
    no_ocr: Annotated[
        bool,
        typer.Option("--no-ocr", help="Disable Mistral OCR (only LaTeX-source PDFs will work)."),
    ] = False,
    verbose: Annotated[bool, typer.Option("-v", "--verbose")] = False,
) -> None:
    """Ingest works listed in SEED into the library."""
    _setup_logging(verbose)
    library_root = _resolve_library(library)
    _bootstrap_env(library_root)
    if not library_root.is_dir():
        err_console.print(
            f"[red]library {library_root} does not exist; "
            f"run [bold]calli init {library_root}[/bold] first[/]"
        )
        raise typer.Exit(code=1)

    if not seed.is_file():
        err_console.print(f"[red]seed file not found: {seed}[/]")
        raise typer.Exit(code=1)

    try:
        candidates = _load_seed_file(seed)
    except (yaml.YAMLError, ValueError) as exc:
        err_console.print(f"[red]invalid seed file: {exc}[/]")
        raise typer.Exit(code=1) from exc

    if not candidates:
        console.print("[yellow]seed file is empty — nothing to do[/]")
        return

    enricher = make_default_enricher()
    embedder: Embedder = NomicEmbedder()
    ocr: OcrProvider | None = None if no_ocr else MistralOcr()
    registry = default_registry(library_root=library_root)

    succeeded, failed = asyncio.run(
        _run_ingest(
            candidates,
            library_root=library_root,
            fail_fast=fail_fast,
            enricher=enricher,
            embedder=embedder,
            ocr=ocr,
            registry=registry,
        )
    )

    color = "green" if failed == 0 else "yellow"
    console.print(
        Panel.fit(
            f"[bold {color}]ingested {succeeded}/{succeeded + failed}[/]"
            + (f"  [red]{failed} failed[/]" if failed else ""),
            title="calli ingest",
        )
    )
    if failed:
        raise typer.Exit(code=1)


# ---------- query ----------


async def _run_query(
    text: str,
    *,
    library_root: Path,
    k: int,
    embedder: Embedder,
) -> None:
    db_path = library_root / "library.db"
    engine = make_engine(f"sqlite:///{db_path}")
    query_vec = await embedder.embed_query(text)

    with make_session(engine) as session:
        hits = search_chunks(session, query_vec, k=k)

    if not hits:
        console.print("[yellow]no results[/]")
        return

    table = Table(title=f"top {len(hits)} results for {text!r}", show_lines=True)
    table.add_column("#", style="dim", no_wrap=True)
    table.add_column("paper", style="bold cyan")
    table.add_column("section", style="magenta")
    table.add_column("snippet")
    table.add_column("dist", style="dim", justify="right")

    for i, hit in enumerate(hits, start=1):
        snippet = hit.chunk.text.strip().replace("\n", " ")[:200]
        if len(hit.chunk.text) > 200:
            snippet += "…"
        title = hit.work.title
        if hit.work.year:
            title = f"{title} ({hit.work.year})"
        table.add_row(
            str(i),
            title,
            hit.chunk.section or "—",
            snippet,
            f"{hit.distance:.3f}",
        )
    console.print(table)


@app.command("query")
def query_cmd(
    text: Annotated[str, typer.Argument(help="The query text.")],
    library: Annotated[
        Path | None,
        typer.Option("--library", "-L", help="Library root (default: ~/Callimachus)."),
    ] = None,
    k: Annotated[int, typer.Option("-k", help="Number of top results.")] = 10,
    verbose: Annotated[bool, typer.Option("-v", "--verbose")] = False,
) -> None:
    """Search the library for chunks similar to TEXT."""
    _setup_logging(verbose)
    library_root = _resolve_library(library)
    _bootstrap_env(library_root)
    if not (library_root / "library.db").is_file():
        err_console.print(
            f"[red]library not found at {library_root}; "
            f"run [bold]calli init[/] and [bold]calli ingest[/] first[/]"
        )
        raise typer.Exit(code=1)

    embedder: Embedder = NomicEmbedder()
    asyncio.run(_run_query(text, library_root=library_root, k=k, embedder=embedder))


# ---------- list ----------


@app.command("list")
def list_cmd(
    library: Annotated[
        Path | None,
        typer.Option("--library", "-L", help="Library root (default: ~/Callimachus)."),
    ] = None,
) -> None:
    """List works in the library."""
    library_root = _resolve_library(library)
    db_path = library_root / "library.db"
    if not db_path.is_file():
        err_console.print(f"[red]library not found at {library_root}[/]")
        raise typer.Exit(code=1)

    engine = make_engine(f"sqlite:///{db_path}")
    with make_session(engine) as session:
        from sqlmodel import select

        rows = list(session.exec(select(Work)).all())

    if not rows:
        console.print("[yellow]library is empty[/]")
        return

    table = Table(title=f"{len(rows)} works in {library_root}", show_lines=False)
    table.add_column("id", style="dim")
    table.add_column("title", style="bold cyan")
    table.add_column("year", justify="right")
    table.add_column("authors", style="magenta")

    for w in rows:
        authors_list = w.authors or []
        authors_str = ", ".join([str(a.get("name", "")) for a in authors_list[:3]])
        if len(authors_list) > 3:
            authors_str += f", +{len(authors_list) - 3}"
        table.add_row(w.id, w.title, str(w.year or "—"), authors_str or "—")
    console.print(table)


# ---------- build (scout → ceremony → orchestrator) ----------


async def _scout_and_ceremony(
    *,
    topic: str,
    registry: SourceRegistry,
    auto: bool,
) -> Plan:
    """Run the scout, then the ceremony (or auto-plan), returning the Plan.

    The ceremony itself renders the angle tree via the prompter when not in
    auto mode — we don't pre-print it here to avoid showing it twice.
    """
    console.print(f"[bold]scout[/] probing angles for [cyan]{topic!r}[/]…")
    tree = await run_scout(topic=topic, registry=registry)
    return run_ceremony(tree, prompter=CliPrompter(), auto=auto)


async def _run_build_from_plan(
    *,
    plan: Plan,
    library_root: Path,
    registry: SourceRegistry,
    no_ocr: bool,
) -> BuildResult:
    """Wire up real hunters/judge/ingest and execute the plan."""
    db_path = library_root / "library.db"
    engine = make_engine(f"sqlite:///{db_path}")

    enricher: EnrichFn = make_default_enricher()
    embedder: Embedder = NomicEmbedder()
    ocr: OcrProvider | None = None if no_ocr else MistralOcr()
    judge_fn = make_default_judge()

    hunt_fn = make_hunt_fn(plan=plan, registry=registry)

    with make_session(engine) as session:
        ingest_fn = make_ingest_fn(
            library_root=library_root,
            session=session,
            registry=registry,
            enricher=enricher,
            embedder=embedder,
            ocr=ocr,
        )
        result = await run_build(
            plan=plan,
            session=session,
            judge_fn=judge_fn,
            hunt_fn=hunt_fn,
            ingest_fn=ingest_fn,
        )
        session.commit()

    return result


def _print_build_result(result: BuildResult, plan: Plan) -> None:
    """Final summary panel for `calli build`."""
    color = "green" if not result.errors else "yellow"
    headline = (
        f"[bold {color}]{result.works_added} works added[/]  "
        f"[dim]({result.candidates_accepted} accepted of "
        f"{result.candidates_judged} judged, "
        f"{result.candidates_after_filter} reachable, "
        f"{result.candidates_total} found)[/]"
    )
    body_lines: list[str] = [headline, "", f"plan: [cyan]{plan.slug}[/]"]
    body_lines.append(f"run id: {result.run_id}")
    body_lines.append(f"elapsed: {result.elapsed_seconds:.1f}s")
    if result.errors:
        body_lines.append("")
        body_lines.append(f"[red]{len(result.errors)} error(s):[/]")
        for err in result.errors[:5]:
            body_lines.append(f"  • {err}")
        if len(result.errors) > 5:
            body_lines.append(f"  [dim]…and {len(result.errors) - 5} more[/]")
    console.print(Panel.fit("\n".join(body_lines), title="calli build"))


@app.command("build")
def build_cmd(
    topic: Annotated[
        str | None,
        typer.Option("--topic", "-t", help="Topic to build a library around (scout + ceremony)."),
    ] = None,
    from_plan: Annotated[
        str | None,
        typer.Option("--from-plan", help="Slug of an existing plan to run (skips scout/ceremony)."),
    ] = None,
    library: Annotated[
        Path | None,
        typer.Option("--library", "-L", help="Library root (default: ~/Callimachus)."),
    ] = None,
    auto: Annotated[
        bool,
        typer.Option(
            "--auto",
            help="Hands-off mode: skip the ceremony and run with all scout angles.",
        ),
    ] = False,
    no_ocr: Annotated[
        bool,
        typer.Option("--no-ocr", help="Disable Mistral OCR (only LaTeX-source PDFs will work)."),
    ] = False,
    verbose: Annotated[bool, typer.Option("-v", "--verbose")] = False,
) -> None:
    """Build a library from a topic: scout → clarify (HITL) → plan → orchestrate.

    Two-step flow:
      calli build --topic "..."           → scout + ceremony → plan.yaml (review then run)
      calli build --from-plan <slug>       → run an existing plan
      calli build --topic "..." --auto     → scout, skip ceremony, run immediately
    """
    if not topic and not from_plan:
        err_console.print("[red]specify either --topic or --from-plan[/]")
        raise typer.Exit(code=1)
    if topic and from_plan:
        err_console.print("[red]--topic and --from-plan are mutually exclusive[/]")
        raise typer.Exit(code=1)

    _setup_logging(verbose)
    library_root = _resolve_library(library)
    _bootstrap_env(library_root)
    if not (library_root / "library.db").is_file():
        err_console.print(
            f"[red]library not found at {library_root}; "
            f"run [bold]calli init {library_root}[/bold] first[/]"
        )
        raise typer.Exit(code=1)

    registry = default_registry(library_root=library_root)

    # Step 1 — produce a Plan (either from scratch or by loading)
    if topic:
        plan = asyncio.run(_scout_and_ceremony(topic=topic, registry=registry, auto=auto))
        saved_at = save_plan(plan, library_root)
        console.print(
            Panel.fit(
                f"[bold green]✓ plan saved[/]\n[dim]{saved_at}[/]",
                title=f"calli build --topic {topic!r}",
            )
        )
        if not auto:
            console.print(
                f"[dim]Review {saved_at} then run: "
                f"[bold]calli build --from-plan {plan.slug}[/][/]"
            )
            return
    else:
        assert from_plan is not None  # narrowed by the early-exit checks above
        try:
            plan = load_plan(library_root, from_plan)
        except FileNotFoundError as exc:
            err_console.print(f"[red]{exc}[/]")
            raise typer.Exit(code=1) from exc

    # Step 2 — orchestrate the plan
    result = asyncio.run(
        _run_build_from_plan(plan=plan, library_root=library_root, registry=registry, no_ocr=no_ocr)
    )
    _print_build_result(result, plan)
    if result.errors and result.works_added == 0:
        raise typer.Exit(code=1)


def main() -> None:
    """Entry point for the `calli` script."""
    app()


if __name__ == "__main__":
    main()
