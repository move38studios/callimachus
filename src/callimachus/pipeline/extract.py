"""Extract stage — turn a downloaded artifact into clean markdown.

LaTeX path: pylatexenc's `LatexNodes2Text` (handles `.tex` directly and
`.tar.gz` archives, picking the largest `.tex` containing `\\documentclass`).

PDF path: routed to an `OcrProvider` (M1.3b — Mistral by default). Images
extracted by the OCR provider are written under `works/<id>/images/` and
the markdown's `![<id>](<id>)` placeholders are rewritten to point at the
saved files.

HTML, plain-text, and other types remain unsupported and raise
`ExtractError`.
"""

from __future__ import annotations

import asyncio
import gzip
import io
import logging
import re
import tarfile
from pathlib import Path
from typing import cast

from pylatexenc.latex2text import LatexNodes2Text

from callimachus.pipeline.ocr.protocols import OcrImage, OcrProvider, OcrUnavailable
from callimachus.pipeline.paths import markdown_path, work_dir

log = logging.getLogger(__name__)


class ExtractError(Exception):
    """Raised when an artifact's content type isn't supported (yet) by extract."""


def _is_latex_archive(content_type: str) -> bool:
    main = content_type.split(";", 1)[0].strip().lower()
    return main in {
        "application/x-tar",
        "application/gzip",
        "application/x-gzip",
        "application/x-eprint-tar",
        "application/x-eprint",
    }


def _is_latex_source(content_type: str) -> bool:
    main = content_type.split(";", 1)[0].strip().lower()
    return main in {"application/x-tex", "text/x-tex"}


def _pick_main_tex(tar: tarfile.TarFile) -> tuple[str, str] | None:
    """Pick the most likely main .tex file from a tar archive.

    Heuristic: the largest .tex file that contains `\\documentclass` wins.
    Falls back to the largest .tex file overall.
    """
    tex_members = [m for m in tar.getmembers() if m.isfile() and m.name.lower().endswith(".tex")]
    if not tex_members:
        return None

    candidates: list[tuple[int, str, str]] = []
    for member in tex_members:
        f = tar.extractfile(member)
        if f is None:
            continue
        try:
            text = f.read().decode("utf-8", errors="replace")
        finally:
            f.close()
        candidates.append((len(text), member.name, text))

    if not candidates:
        return None

    # Prefer ones with \documentclass, then by descending size
    with_docclass = [c for c in candidates if "\\documentclass" in c[2]]
    pool = with_docclass or candidates
    pool.sort(key=lambda c: -c[0])
    _, name, text = pool[0]
    return name, text


def _read_latex_source(artifact_bytes: bytes, content_type: str) -> str:
    """Pull the main LaTeX source out of a tarball, gzip, or raw .tex."""
    if _is_latex_source(content_type):
        return artifact_bytes.decode("utf-8", errors="replace")

    # arxiv's e-print is most often a gzipped tar; sometimes plain gzip
    # over a single .tex (though rarer these days).
    bio = io.BytesIO(artifact_bytes)
    try:
        with tarfile.open(fileobj=bio, mode="r:*") as tar:
            picked = _pick_main_tex(tar)
            if picked is None:
                raise ExtractError("extract: archive contains no .tex files we can use")
            name, text = picked
            log.debug("extract: picked main TeX file %r (%d chars)", name, len(text))
            return text
    except tarfile.TarError:
        # Not a tar — try plain gzip wrapping a .tex
        try:
            inner = gzip.decompress(artifact_bytes)
            return inner.decode("utf-8", errors="replace")
        except (OSError, EOFError) as exc:
            raise ExtractError(
                f"extract: artifact is not a valid tar or gzip archive: {exc}"
            ) from exc


def latex_to_markdown(latex_text: str) -> str:
    """Convert a LaTeX document body to plain-text-ish markdown.

    pylatexenc gives plain text with reasonable structure preservation
    (paragraphs, sections, math via Unicode). We treat that as "good
    enough markdown" for v0.1 — enrichment + embedding can work with it.
    """
    converter = LatexNodes2Text(
        keep_comments=False,
        math_mode="text",  # render math as Unicode where possible
    )
    # pylatexenc has no type stubs; everything coming out of it is `Unknown`
    # so cast through `object` to a guaranteed `str`.
    raw_text: object = converter.latex_to_text(latex_text)  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
    text = cast("str", raw_text)
    # Normalise multiple blank lines down to two
    out_lines: list[str] = []
    blank_streak = 0
    for line in text.splitlines():
        if not line.strip():
            blank_streak += 1
            if blank_streak <= 1:
                out_lines.append("")
        else:
            blank_streak = 0
            out_lines.append(line.rstrip())
    # Strip leading/trailing blank lines
    while out_lines and not out_lines[0]:
        out_lines.pop(0)
    while out_lines and not out_lines[-1]:
        out_lines.pop()
    return "\n".join(out_lines) + "\n"


def _is_pdf(content_type: str) -> bool:
    return content_type.split(";", 1)[0].strip().lower() == "application/pdf"


def _rewrite_image_refs(markdown: str, prefix: str) -> str:
    """Rewrite `![alt](name)` → `![alt](<prefix>/name)` for non-URL refs.

    Leaves http(s):// and data: URLs alone. Used to redirect Mistral's
    placeholder image references to the on-disk `images/` subfolder.
    """
    pattern = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)\)")

    def _sub(match: re.Match[str]) -> str:
        alt, target = match.group(1), match.group(2)
        if target.startswith(("http://", "https://", "data:", "/", "#")):
            return match.group(0)
        # Don't double-prefix
        if target.startswith(prefix):
            return match.group(0)
        return f"![{alt}]({prefix}{target})"

    return pattern.sub(_sub, markdown)


async def extract_to_markdown(
    library_root: Path,
    work_id: str,
    artifact_path: Path,
    content_type: str,
    *,
    ocr: OcrProvider | None = None,
) -> Path:
    """Read the downloaded artifact, extract markdown, write `paper.md`.

    LaTeX archives + raw `.tex` are handled in-process. PDFs route to the
    `ocr` provider (required for the PDF path; raises `ExtractError` if
    `ocr=None` is passed for a PDF artifact).

    Idempotent: if `paper.md` already exists, skip and return the path.

    Returns the path to the written markdown file.
    """
    dest = markdown_path(library_root, work_id)
    if dest.exists():
        log.debug("extract_to_markdown: %s already exists, skipping", dest)
        return dest

    artifact_bytes = await asyncio.to_thread(artifact_path.read_bytes)

    if _is_latex_archive(content_type) or _is_latex_source(content_type):
        latex_text = _read_latex_source(artifact_bytes, content_type)
        markdown = latex_to_markdown(latex_text)
    elif _is_pdf(content_type):
        if ocr is None:
            raise ExtractError(
                f"extract: content type {content_type!r} requires an OCR provider; "
                f"pass ocr=MistralOcr() (or another OcrProvider)."
            )
        try:
            result = await ocr.extract(artifact_bytes, content_type)
        except OcrUnavailable as exc:
            raise ExtractError(f"extract: OCR provider failed: {exc}") from exc
        markdown = _persist_ocr_images(library_root, work_id, result.markdown, result.images)
    else:
        raise ExtractError(
            f"extract: content type {content_type!r} not supported (LaTeX and PDF only for now)."
        )

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(markdown)
    log.debug("extract_to_markdown: wrote %d chars of markdown to %s", len(markdown), dest)
    return dest


def _persist_ocr_images(
    library_root: Path,
    work_id: str,
    markdown: str,
    images: list[OcrImage],
) -> str:
    """Write OCR-extracted images to `works/<id>/images/` and rewrite refs."""
    if not images:
        return markdown
    images_dir = work_dir(library_root, work_id) / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    for img in images:
        (images_dir / img.id).write_bytes(img.bytes_)
    return _rewrite_image_refs(markdown, "images/")
