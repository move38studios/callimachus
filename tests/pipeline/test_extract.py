"""Tests for the extract stage (LaTeX → markdown)."""

from __future__ import annotations

import io
import tarfile
from pathlib import Path

import pytest

from callimachus.pipeline.download import download_to_library
from callimachus.pipeline.extract import (
    ExtractError,
    extract_to_markdown,
    latex_to_markdown,
)
from callimachus.pipeline.paths import markdown_path
from callimachus.sources import ResolvedFile

LATEX_FIXTURE = r"""
\documentclass{article}
\title{Denoising Diffusion Probabilistic Models}
\author{Jonathan Ho \and Ajay Jain \and Pieter Abbeel}
\begin{document}
\maketitle

\begin{abstract}
We present high quality image synthesis results using diffusion probabilistic
models, a class of latent variable models inspired by considerations from
nonequilibrium thermodynamics.
\end{abstract}

\section{Introduction}
Deep generative models have demonstrated impressive results.
The forward process is parameterised as a Markov chain that adds Gaussian
noise: $q(x_t | x_{t-1}) = \mathcal{N}(x_t; \sqrt{1 - \beta_t} x_{t-1}, \beta_t I)$.

\section{Method}
We train using a variational bound on the log-likelihood.

\end{document}
"""


def _make_latex_targz(filename: str = "main.tex", content: str = LATEX_FIXTURE) -> bytes:
    """Build an in-memory gzipped tar containing one .tex file."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        data = content.encode("utf-8")
        info = tarfile.TarInfo(filename)
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def _make_multi_file_targz() -> bytes:
    """Tar with several .tex files; only one has \\documentclass."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        files = {
            "intro.tex": "Just some intro text without documentclass.",
            "main.tex": LATEX_FIXTURE,  # the real main file
            "appendix.tex": "Random appendix content with no documentclass.",
        }
        for name, content in files.items():
            data = content.encode("utf-8")
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


# ---------- latex_to_markdown ----------


def test_latex_to_markdown_extracts_section_headers() -> None:
    md = latex_to_markdown(LATEX_FIXTURE).lower()
    # pylatexenc uppercases section headings (renders as '§ INTRODUCTION');
    # we just want to confirm the content survived the conversion.
    assert "introduction" in md
    assert "method" in md


def test_latex_to_markdown_extracts_abstract_text() -> None:
    md = latex_to_markdown(LATEX_FIXTURE)
    assert "diffusion probabilistic models" in md.lower()
    assert "nonequilibrium thermodynamics" in md.lower()


def test_latex_to_markdown_renders_math_as_unicode() -> None:
    """Math mode → Unicode where pylatexenc supports it."""
    md = latex_to_markdown(LATEX_FIXTURE)
    # The Greek letter beta should render
    assert "β" in md or "beta" in md.lower()


def test_latex_to_markdown_collapses_excessive_blank_lines() -> None:
    noisy = "Para 1\n\n\n\n\n\nPara 2\n\n\n\n\nPara 3\n"
    md = latex_to_markdown(noisy)
    # Allow at most one blank line between paragraphs
    assert "\n\n\n" not in md


def test_latex_to_markdown_strips_leading_and_trailing_blanks() -> None:
    md = latex_to_markdown("\n\n\nHello\n\n\n")
    assert md.startswith("Hello")
    assert md.endswith("\n")


# ---------- extract_to_markdown end-to-end ----------


def test_extract_from_targz_writes_paper_md(tmp_path: Path) -> None:
    rf = ResolvedFile(
        candidate_id="arxiv:2006.11239",
        bytes_=_make_latex_targz(),
        content_type="application/x-eprint-tar",
        source_url="https://arxiv.org/e-print/2006.11239",
        resolved_by="arxiv",
    )
    artifact_path = download_to_library(tmp_path, "ho-2020", rf)
    md_path = extract_to_markdown(tmp_path, "ho-2020", artifact_path, rf.content_type)
    assert md_path == markdown_path(tmp_path, "ho-2020")
    text = md_path.read_text().lower()
    assert "introduction" in text
    assert "method" in text
    assert "diffusion probabilistic models" in text


def test_extract_picks_main_tex_from_multi_file_archive(tmp_path: Path) -> None:
    rf = ResolvedFile(
        candidate_id="arxiv:test",
        bytes_=_make_multi_file_targz(),
        content_type="application/x-eprint-tar",
        source_url="https://arxiv.org/e-print/test",
        resolved_by="arxiv",
    )
    artifact_path = download_to_library(tmp_path, "x", rf)
    md_path = extract_to_markdown(tmp_path, "x", artifact_path, rf.content_type)
    text = md_path.read_text().lower()
    # Should pick main.tex (the one with \documentclass), not the others
    assert "introduction" in text
    assert "appendix" not in text


def test_extract_from_raw_tex_works(tmp_path: Path) -> None:
    rf = ResolvedFile(
        candidate_id="x",
        bytes_=LATEX_FIXTURE.encode("utf-8"),
        content_type="application/x-tex",
        source_url="https://example.org/x.tex",
        resolved_by="test",
    )
    artifact_path = download_to_library(tmp_path, "x", rf)
    md_path = extract_to_markdown(tmp_path, "x", artifact_path, rf.content_type)
    text = md_path.read_text().lower()
    assert "introduction" in text


def test_extract_pdf_raises_extract_error_for_now(tmp_path: Path) -> None:
    rf = ResolvedFile(
        candidate_id="x",
        bytes_=b"%PDF-1.4 stub",
        content_type="application/pdf",
        source_url="https://example.org/x.pdf",
        resolved_by="test",
    )
    artifact_path = download_to_library(tmp_path, "x", rf)
    with pytest.raises(ExtractError, match=r"not supported in M1\.3a"):
        extract_to_markdown(tmp_path, "x", artifact_path, rf.content_type)


def test_extract_is_idempotent(tmp_path: Path) -> None:
    rf = ResolvedFile(
        candidate_id="x",
        bytes_=_make_latex_targz(),
        content_type="application/x-eprint-tar",
        source_url="https://example.org/e-print/x",
        resolved_by="arxiv",
    )
    artifact_path = download_to_library(tmp_path, "x", rf)
    first = extract_to_markdown(tmp_path, "x", artifact_path, rf.content_type)
    mtime_after_first = first.stat().st_mtime_ns
    second = extract_to_markdown(tmp_path, "x", artifact_path, rf.content_type)
    assert second == first
    assert second.stat().st_mtime_ns == mtime_after_first


def test_extract_archive_with_no_tex_files_raises(tmp_path: Path) -> None:
    """Archive contains no .tex files."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        data = b"some random content"
        info = tarfile.TarInfo("README.txt")
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))
    rf = ResolvedFile(
        candidate_id="x",
        bytes_=buf.getvalue(),
        content_type="application/x-eprint-tar",
        source_url="https://example.org/x",
        resolved_by="arxiv",
    )
    artifact_path = download_to_library(tmp_path, "x", rf)
    with pytest.raises(ExtractError, match=r"no \.tex files"):
        extract_to_markdown(tmp_path, "x", artifact_path, rf.content_type)
