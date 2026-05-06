"""Tests for the OCR provider abstraction.

The MistralOcr-specific tests live in `test_ocr_mistral.py`; this file
exercises the Protocol shape, the data-URL parser, and the extract.py
PDF path with a fake provider so we can verify pipeline integration
without touching the network.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from callimachus.pipeline.download import download_to_library
from callimachus.pipeline.extract import (
    _rewrite_image_refs,  # pyright: ignore[reportPrivateUsage]
    extract_to_markdown,
)
from callimachus.pipeline.ocr import (
    MistralOcr,
    OcrImage,
    OcrProvider,
    OcrResult,
    OcrUnavailable,
)
from callimachus.pipeline.ocr.mistral import parse_data_url
from callimachus.sources import ResolvedFile

# A 1x1 transparent PNG, base64-encoded, as a stand-in for an extracted figure.
_PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000d49444154789c63000100000005000150d63b290000000049454e44ae426082"
)


# ---------- _parse_data_url ----------


def test_parse_data_url_decodes_jpeg() -> None:
    import base64

    payload = base64.b64encode(b"\xff\xd8\xff\xe0 stub jpeg").decode("ascii")
    ct, data = parse_data_url(f"data:image/jpeg;base64,{payload}")
    assert ct == "image/jpeg"
    assert data == b"\xff\xd8\xff\xe0 stub jpeg"


def test_parse_data_url_lowercases_content_type() -> None:
    import base64

    payload = base64.b64encode(b"x").decode("ascii")
    ct, _ = parse_data_url(f"data:Image/PNG;base64,{payload}")
    assert ct == "image/png"


def test_parse_data_url_rejects_non_data_url() -> None:
    with pytest.raises(ValueError, match="not a base64 data URL"):
        parse_data_url("https://example.org/img.png")


def test_parse_data_url_rejects_bad_base64() -> None:
    with pytest.raises(ValueError, match="failed to decode"):
        parse_data_url("data:image/png;base64,!!!not base64!!!")


# ---------- protocol shape ----------


def test_mistral_ocr_satisfies_protocol() -> None:
    plugin = MistralOcr(api_key="dummy-not-actually-used-here")
    assert isinstance(plugin, OcrProvider)
    assert plugin.name == "mistral"


def test_mistral_ocr_no_key_raises_on_use() -> None:
    """No API key + no client + .extract() == OcrUnavailable."""
    plugin = MistralOcr(api_key=None, client=None)

    async def go() -> None:
        with pytest.raises(OcrUnavailable, match="no API key"):
            await plugin.extract(b"%PDF stub", "application/pdf")

    import asyncio

    asyncio.run(go())


# ---------- _rewrite_image_refs ----------


def test_rewrite_image_refs_prefixes_relative_paths() -> None:
    md = "Here is figure 1: ![img-0.jpeg](img-0.jpeg) and figure 2: ![](img-1.png)."
    out = _rewrite_image_refs(md, "images/")
    assert out == (
        "Here is figure 1: ![img-0.jpeg](images/img-0.jpeg) and figure 2: ![](images/img-1.png)."
    )


def test_rewrite_image_refs_leaves_absolute_urls_alone() -> None:
    md = "![](https://example.org/x.png) ![](data:image/png;base64,abc)"
    out = _rewrite_image_refs(md, "images/")
    assert out == md


def test_rewrite_image_refs_does_not_double_prefix() -> None:
    md = "![](images/foo.jpg)"
    assert _rewrite_image_refs(md, "images/") == md


# ---------- extract_to_markdown PDF path with a fake OcrProvider ----------


class _FakeOcr:
    """Stand-in OcrProvider that returns a canned OcrResult."""

    name: str = "fake"

    def __init__(self, result: OcrResult) -> None:
        self._result = result

    async def extract(self, artifact_bytes: bytes, content_type: str) -> OcrResult:
        del artifact_bytes, content_type
        return self._result


async def test_extract_pdf_via_fake_ocr_writes_markdown_and_images(tmp_path: Path) -> None:
    fake_result = OcrResult(
        markdown=(
            "# Test Doc\n\n"
            "This is a paragraph.\n\n"
            "Here's a figure: ![img-0.png](img-0.png)\n\n"
            "And another: ![Figure 2](img-1.png)\n"
        ),
        images=[
            OcrImage(id="img-0.png", bytes_=_PNG_BYTES, content_type="image/png"),
            OcrImage(id="img-1.png", bytes_=_PNG_BYTES, content_type="image/png"),
        ],
        pages=2,
        provider="fake",
    )
    fake = _FakeOcr(fake_result)

    rf = ResolvedFile(
        candidate_id="x",
        bytes_=b"%PDF-1.4 stub",
        content_type="application/pdf",
        source_url="https://example.org/x.pdf",
        resolved_by="test",
    )
    artifact_path = download_to_library(tmp_path, "x", rf)
    md_path = await extract_to_markdown(tmp_path, "x", artifact_path, rf.content_type, ocr=fake)

    # Markdown was rewritten so image refs point at the images/ subfolder
    text = md_path.read_text()
    assert "![img-0.png](images/img-0.png)" in text
    assert "![Figure 2](images/img-1.png)" in text

    # Images written to disk
    images_dir = tmp_path / "works" / "x" / "images"
    assert (images_dir / "img-0.png").read_bytes() == _PNG_BYTES
    assert (images_dir / "img-1.png").read_bytes() == _PNG_BYTES


async def test_extract_pdf_handles_empty_image_list(tmp_path: Path) -> None:
    """A PDF with no figures: markdown is written verbatim, no images dir."""
    fake = _FakeOcr(OcrResult(markdown="just text\n", images=[], pages=1, provider="fake"))
    rf = ResolvedFile(
        candidate_id="x",
        bytes_=b"%PDF stub",
        content_type="application/pdf",
        source_url="https://example.org/x",
        resolved_by="test",
    )
    artifact_path = download_to_library(tmp_path, "x", rf)
    md_path = await extract_to_markdown(tmp_path, "x", artifact_path, rf.content_type, ocr=fake)
    assert md_path.read_text() == "just text\n"
    assert not (tmp_path / "works" / "x" / "images").exists()


async def test_extract_pdf_propagates_ocr_failure_as_extract_error(
    tmp_path: Path,
) -> None:
    class _Broken:
        name: str = "broken"

        async def extract(self, artifact_bytes: bytes, content_type: str) -> OcrResult:
            del artifact_bytes, content_type
            raise OcrUnavailable("rate limited")

    rf = ResolvedFile(
        candidate_id="x",
        bytes_=b"%PDF stub",
        content_type="application/pdf",
        source_url="https://example.org/x",
        resolved_by="test",
    )
    artifact_path = download_to_library(tmp_path, "x", rf)
    from callimachus.pipeline.extract import ExtractError

    with pytest.raises(ExtractError, match="OCR provider failed"):
        await extract_to_markdown(tmp_path, "x", artifact_path, rf.content_type, ocr=_Broken())
