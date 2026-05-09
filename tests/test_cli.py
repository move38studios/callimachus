"""Tests for the calli CLI.

Uses Typer's `CliRunner`. Each test sets `CALLIMACHUS_LIBRARY` to a
tmp_path so we never touch the real `~/Callimachus`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from callimachus.cli import (
    _candidate_from_yaml_entry,  # pyright: ignore[reportPrivateUsage]
    _load_seed_file,  # pyright: ignore[reportPrivateUsage]
    app,
)


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def library_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Point CALLIMACHUS_LIBRARY at tmp_path so commands stay sandboxed."""
    library_root = tmp_path / "lib"
    monkeypatch.setenv("CALLIMACHUS_LIBRARY", str(library_root))
    return library_root


# ---------- seed file parsing ----------


def test_candidate_from_arxiv_entry() -> None:
    c = _candidate_from_yaml_entry({"arxiv": "2006.11239"}, source="t")
    assert c.arxiv_id == "2006.11239"
    assert c.source_url == "https://arxiv.org/abs/2006.11239"
    assert c.kind == "paper"


def test_candidate_from_doi_entry() -> None:
    c = _candidate_from_yaml_entry({"doi": "10.1234/foo"}, source="t")
    assert c.doi == "10.1234/foo"
    assert "doi.org" in c.source_url


def test_candidate_from_url_entry() -> None:
    c = _candidate_from_yaml_entry({"url": "https://example.org/paper.pdf"}, source="t")
    assert c.source_url == "https://example.org/paper.pdf"
    assert c.doi is None
    assert c.arxiv_id is None


def test_candidate_from_full_entry() -> None:
    c = _candidate_from_yaml_entry(
        {
            "title": "Custom Paper",
            "source_url": "https://example.org/x",
            "authors": ["A. Author", "B. Author"],
            "year": 2024,
            "venue": "JMLR",
        },
        source="t",
    )
    assert c.title == "Custom Paper"
    assert c.authors == ["A. Author", "B. Author"]
    assert c.year == 2024
    assert c.venue == "JMLR"


def test_candidate_from_invalid_entry_raises() -> None:
    with pytest.raises(ValueError, match="must include one of"):
        _candidate_from_yaml_entry({"random": "fields"}, source="t")


def test_load_seed_file_parses_list(tmp_path: Path) -> None:
    seed = tmp_path / "seed.yaml"
    seed.write_text(
        """
- arxiv: "2006.11239"
- doi: "10.1234/foo"
- url: "https://example.org/x.pdf"
""".strip()
    )
    candidates = _load_seed_file(seed)
    assert len(candidates) == 3
    assert candidates[0].arxiv_id == "2006.11239"
    assert candidates[1].doi == "10.1234/foo"
    assert candidates[2].source_url == "https://example.org/x.pdf"


def test_load_seed_file_rejects_non_list(tmp_path: Path) -> None:
    seed = tmp_path / "seed.yaml"
    seed.write_text("a: 1\nb: 2\n")
    with pytest.raises(ValueError, match="must be a YAML list"):
        _load_seed_file(seed)


# ---------- init ----------


def test_init_creates_library_layout(runner: CliRunner, tmp_path: Path) -> None:
    target = tmp_path / "my_library"
    result = runner.invoke(app, ["init", str(target)])
    assert result.exit_code == 0, result.output
    assert (target / "library.db").is_file()
    assert (target / "works").is_dir()
    assert (target / "collections").is_dir()
    assert (target / "archive").is_dir()
    assert (target / "plugins").is_dir()
    assert (target / ".callimachus").is_dir()


def test_init_uses_env_var_when_no_arg(runner: CliRunner, library_env: Path) -> None:
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0, result.output
    assert (library_env / "library.db").is_file()


def test_init_is_idempotent(runner: CliRunner, tmp_path: Path) -> None:
    target = tmp_path / "lib"
    assert runner.invoke(app, ["init", str(target)]).exit_code == 0
    # Second run should not error
    second = runner.invoke(app, ["init", str(target)])
    assert second.exit_code == 0


# ---------- query ----------


def test_query_errors_when_library_missing(runner: CliRunner, library_env: Path) -> None:
    result = runner.invoke(app, ["query", "anything"])
    assert result.exit_code == 1
    assert "library not found" in result.stderr


def test_query_on_empty_library_returns_no_results(
    runner: CliRunner, library_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner.invoke(app, ["init"])

    # Stub the embedder so we don't load nomic-v1.5 in tests
    class _StubEmbedder:
        name: str = "stub"

        async def embed_documents(self, texts: list[str]) -> list[list[float]]:
            return [[0.1] * 768 for _ in texts]

        async def embed_query(self, text: str) -> list[float]:
            del text
            return [0.1] * 768

    import callimachus.cli as cli_module

    monkeypatch.setattr(cli_module, "NomicEmbedder", _StubEmbedder)

    result = runner.invoke(app, ["query", "anything"])
    assert result.exit_code == 0
    assert "no results" in result.output


# ---------- ingest (with stubs) ----------


def test_ingest_errors_when_seed_missing(runner: CliRunner, library_env: Path) -> None:
    runner.invoke(app, ["init"])
    result = runner.invoke(app, ["ingest", "/nope/seed.yaml"])
    assert result.exit_code == 1
    assert "seed file not found" in result.stderr


def test_ingest_errors_when_library_missing(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CALLIMACHUS_LIBRARY", str(tmp_path / "missing_lib"))
    seed = tmp_path / "seed.yaml"
    seed.write_text("- arxiv: 2006.11239\n")
    result = runner.invoke(app, ["ingest", str(seed)])
    assert result.exit_code == 1
    assert "library" in result.stderr.lower()


def test_ingest_empty_seed_succeeds_quietly(runner: CliRunner, library_env: Path) -> None:
    runner.invoke(app, ["init"])
    seed = library_env.parent / "seed.yaml"
    seed.write_text("[]\n")
    result = runner.invoke(app, ["ingest", str(seed)])
    assert result.exit_code == 0
    assert "nothing to do" in result.output


def test_ingest_invalid_yaml_errors(runner: CliRunner, library_env: Path) -> None:
    runner.invoke(app, ["init"])
    seed = library_env.parent / "seed.yaml"
    seed.write_text("not: a list\n")
    result = runner.invoke(app, ["ingest", str(seed)])
    assert result.exit_code == 1
    assert "invalid seed file" in result.stderr


# ---------- list ----------


def test_list_on_empty_library(runner: CliRunner, library_env: Path) -> None:
    runner.invoke(app, ["init"])
    result = runner.invoke(app, ["list"])
    assert result.exit_code == 0
    assert "library is empty" in result.output


def test_list_errors_when_library_missing(runner: CliRunner, library_env: Path) -> None:
    result = runner.invoke(app, ["list"])
    assert result.exit_code == 1
    assert "library not found" in result.stderr


# ---------- end-to-end ingest with all stubs ----------


def test_ingest_end_to_end_with_stubs(
    runner: CliRunner,
    library_env: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stub everything network-bound; verify the CLI wires the pieces correctly."""
    runner.invoke(app, ["init"])

    import io
    import tarfile

    from callimachus.pipeline.enrich import Enrichment
    from callimachus.sources import ResolvedFile

    latex = (
        r"\documentclass{article}"
        "\n"
        r"\begin{document}"
        "\n"
        r"\section{Intro}"
        "\n"
        "Body content. " * 50 + "\n" + r"\end{document}" + "\n"
    )
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        data = latex.encode()
        info = tarfile.TarInfo("main.tex")
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))
    targz_bytes = buf.getvalue()

    # Stub registry: returns canned LaTeX archive
    class _StubResolver:
        name: str = "stub"
        enabled: bool = True

        async def confidence(self, candidate: Any) -> float:
            return 1.0

        async def resolve(self, candidate: Any) -> ResolvedFile:
            return ResolvedFile(
                candidate_id=candidate.candidate_id,
                bytes_=targz_bytes,
                content_type="application/x-eprint-tar",
                source_url=candidate.source_url,
                resolved_by=self.name,
            )

    def _stub_default_registry(library_root: Path | None = None) -> Any:
        del library_root
        from callimachus.sources import SourceRegistry

        reg = SourceRegistry()
        reg.register_resolver(_StubResolver())  # type: ignore[arg-type]
        return reg

    # Stub enricher
    async def _stub_enrich(text: str) -> Enrichment:
        del text
        return Enrichment(
            title="Test Paper",
            authors=["Test Author"],
            year=2024,
            summary="A summary of a paper that is at least twenty characters long.",
        )

    def _stub_make_default_enricher(model: str = "x") -> Any:
        del model
        return _stub_enrich

    # Stub embedder
    class _StubEmbedder:
        name: str = "stub"

        async def embed_documents(self, texts: list[str]) -> list[list[float]]:
            return [[0.1] * 768 for _ in texts]

        async def embed_query(self, text: str) -> list[float]:
            del text
            return [0.1] * 768

    import callimachus.cli as cli_module

    monkeypatch.setattr(cli_module, "default_registry", _stub_default_registry)
    monkeypatch.setattr(cli_module, "make_default_enricher", _stub_make_default_enricher)
    monkeypatch.setattr(cli_module, "NomicEmbedder", _StubEmbedder)

    seed = tmp_path / "seed.yaml"
    seed.write_text("- arxiv: 2006.11239\n")

    result = runner.invoke(app, ["ingest", str(seed), "--no-ocr"])
    assert result.exit_code == 0, f"output: {result.output}\nstderr: {result.stderr}"
    assert "ingested 1/1" in result.output

    # Verify on disk
    assert (library_env / "works" / "arxiv-2006-11239" / "paper.md").is_file()
    assert (library_env / "works" / "arxiv-2006-11239" / "metadata.yaml").is_file()

    # `list` shows it
    list_result = runner.invoke(app, ["list"])
    assert list_result.exit_code == 0
    assert "Test Paper" in list_result.output
