"""Tests for path helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from callimachus.pipeline.paths import (
    DEFAULT_LIBRARY_ROOT,
    extension_for_content_type,
    get_library_root,
    markdown_path,
    original_path,
    work_dir,
)


def test_default_library_root_is_home_callimachus(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CALLIMACHUS_LIBRARY", raising=False)
    assert get_library_root() == DEFAULT_LIBRARY_ROOT


def test_env_overrides_library_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CALLIMACHUS_LIBRARY", str(tmp_path))
    assert get_library_root() == tmp_path.resolve()


def test_explicit_override_wins(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CALLIMACHUS_LIBRARY", "/nope/should/be/ignored")
    assert get_library_root(override=tmp_path) == tmp_path.resolve()


def test_work_dir_layout(tmp_path: Path) -> None:
    assert work_dir(tmp_path, "ho-2020-ddpm") == tmp_path / "works" / "ho-2020-ddpm"


@pytest.mark.parametrize(
    "content_type, expected_ext",
    [
        ("application/pdf", ".pdf"),
        ("application/pdf; charset=binary", ".pdf"),
        ("application/x-tar", ".tar.gz"),
        ("application/gzip", ".tar.gz"),
        ("application/x-eprint-tar", ".tar.gz"),
        ("application/x-tex", ".tex"),
        ("text/x-tex", ".tex"),
        ("text/html", ".html"),
        ("text/plain", ".txt"),
        ("application/octet-stream", ".bin"),
        ("APPLICATION/PDF", ".pdf"),  # case-insensitive
    ],
)
def test_extension_for_content_type(content_type: str, expected_ext: str) -> None:
    assert extension_for_content_type(content_type) == expected_ext


def test_original_path_uses_correct_extension(tmp_path: Path) -> None:
    p = original_path(tmp_path, "x", "application/pdf")
    assert p.name == "original.pdf"
    assert p.parent == tmp_path / "works" / "x"


def test_markdown_path(tmp_path: Path) -> None:
    p = markdown_path(tmp_path, "x")
    assert p == tmp_path / "works" / "x" / "paper.md"
