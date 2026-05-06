"""Tests for the download stage."""

from __future__ import annotations

from pathlib import Path

from callimachus.pipeline.download import download_to_library
from callimachus.sources import ResolvedFile


def _resolved(content: bytes = b"%PDF stub", content_type: str = "application/pdf") -> ResolvedFile:
    return ResolvedFile(
        candidate_id="doi:10.1/test",
        bytes_=content,
        content_type=content_type,
        source_url="https://example.org/x.pdf",
        resolved_by="test",
    )


def test_download_writes_bytes_to_correct_location(tmp_path: Path) -> None:
    rf = _resolved(content=b"hello world")
    dest = download_to_library(tmp_path, "ho-2020", rf)
    assert dest == tmp_path / "works" / "ho-2020" / "original.pdf"
    assert dest.read_bytes() == b"hello world"


def test_download_uses_extension_from_content_type(tmp_path: Path) -> None:
    rf = _resolved(content_type="application/x-eprint-tar")
    dest = download_to_library(tmp_path, "x", rf)
    assert dest.suffix == ".gz"  # .tar.gz
    assert dest.name == "original.tar.gz"


def test_download_creates_intermediate_directories(tmp_path: Path) -> None:
    rf = _resolved()
    dest = download_to_library(tmp_path, "deeply/nested/id", rf)
    assert dest.parent.is_dir()
    assert dest.exists()


def test_download_is_idempotent(tmp_path: Path) -> None:
    rf = _resolved(content=b"same bytes")
    first = download_to_library(tmp_path, "x", rf)
    mtime_after_first = first.stat().st_mtime_ns
    second = download_to_library(tmp_path, "x", rf)
    assert second == first
    # Idempotent skip means we didn't rewrite the file
    assert second.stat().st_mtime_ns == mtime_after_first


def test_download_overwrites_when_size_differs(tmp_path: Path) -> None:
    download_to_library(tmp_path, "x", _resolved(content=b"first"))
    second = download_to_library(tmp_path, "x", _resolved(content=b"different bytes"))
    assert second.read_bytes() == b"different bytes"
