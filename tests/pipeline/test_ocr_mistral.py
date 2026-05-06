"""Tests for the MistralOcr provider — mocks the Mistral SDK client."""

from __future__ import annotations

import base64
from typing import Any

import pytest

from callimachus.pipeline.ocr import MistralOcr, OcrUnavailable

_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000d49444154789c63000100000005000150d63b290000000049454e44ae426082"
)


def _data_url(content_type: str, data: bytes) -> str:
    return f"data:{content_type};base64,{base64.b64encode(data).decode('ascii')}"


# ----- fake Mistral SDK objects -----


class _FakeUploaded:
    def __init__(self, file_id: str = "file_123") -> None:
        self.id = file_id


class _FakeSignedUrl:
    def __init__(self, url: str = "https://files.mistral.ai/file_123/signed") -> None:
        self.url = url


class _FakeOcrImage:
    def __init__(self, img_id: str, content_type: str, raw: bytes) -> None:
        self.id = img_id
        self.image_base64 = _data_url(content_type, raw)


class _FakeOcrPage:
    def __init__(self, markdown: str, images: list[_FakeOcrImage] | None = None) -> None:
        self.markdown = markdown
        self.images = images or []


class _FakeOcrResponse:
    def __init__(self, pages: list[_FakeOcrPage]) -> None:
        self.pages = pages


class _FakeFiles:
    def __init__(self) -> None:
        self.uploaded: list[dict[str, Any]] = []
        self.deleted: list[str] = []

    def upload(self, *, file: dict[str, Any], purpose: str) -> _FakeUploaded:
        self.uploaded.append({"file": file, "purpose": purpose})
        return _FakeUploaded()

    def get_signed_url(self, *, file_id: str) -> _FakeSignedUrl:
        del file_id
        return _FakeSignedUrl()

    def delete(self, *, file_id: str) -> None:
        self.deleted.append(file_id)


class _FakeOcrApi:
    def __init__(self, response: _FakeOcrResponse) -> None:
        self._response = response
        self.last_call: dict[str, Any] | None = None

    def process(
        self,
        *,
        model: str,
        document: dict[str, Any],
        include_image_base64: bool,
    ) -> _FakeOcrResponse:
        self.last_call = {
            "model": model,
            "document": document,
            "include_image_base64": include_image_base64,
        }
        return self._response


class _FakeMistralClient:
    def __init__(self, ocr_response: _FakeOcrResponse) -> None:
        self.files = _FakeFiles()
        self.ocr = _FakeOcrApi(ocr_response)


# ----- the actual tests -----


async def test_extract_pdf_uploads_signs_and_deletes() -> None:
    fake_response = _FakeOcrResponse(
        pages=[
            _FakeOcrPage(
                markdown="Page 1 content\n\n![img-0.png](img-0.png)\n",
                images=[_FakeOcrImage("img-0.png", "image/png", _PNG)],
            ),
            _FakeOcrPage(markdown="Page 2 content"),
        ]
    )
    client = _FakeMistralClient(fake_response)
    plugin = MistralOcr(client=client)  # type: ignore[arg-type]

    result = await plugin.extract(b"%PDF stub bytes", "application/pdf")

    # Upload: file uploaded with purpose=ocr
    assert len(client.files.uploaded) == 1
    assert client.files.uploaded[0]["purpose"] == "ocr"

    # OCR call: document_url + include_image_base64
    last = client.ocr.last_call
    assert last is not None
    assert last["model"] == "mistral-ocr-latest"
    assert last["document"]["type"] == "document_url"
    assert "signed" in last["document"]["document_url"]
    assert last["include_image_base64"] is True

    # Cleanup: file_id was deleted
    assert client.files.deleted == ["file_123"]

    # Result shape
    assert "Page 1 content" in result.markdown
    assert "Page 2 content" in result.markdown
    assert result.pages == 2
    assert result.provider == "mistral"
    assert len(result.images) == 1
    assert result.images[0].id == "img-0.png"
    assert result.images[0].bytes_ == _PNG
    assert result.images[0].content_type == "image/png"


async def test_extract_pdf_deletes_file_even_when_ocr_raises() -> None:
    """Cleanup must run even on OCR errors."""

    class _ExplodingOcr(_FakeOcrApi):
        def process(
            self,
            *,
            model: str,
            document: dict[str, Any],
            include_image_base64: bool,
        ) -> _FakeOcrResponse:
            del model, document, include_image_base64
            raise RuntimeError("Mistral exploded")

    client = _FakeMistralClient(_FakeOcrResponse([]))
    client.ocr = _ExplodingOcr(_FakeOcrResponse([]))

    plugin = MistralOcr(client=client)  # type: ignore[arg-type]
    with pytest.raises(OcrUnavailable, match="RuntimeError"):
        await plugin.extract(b"%PDF stub", "application/pdf")
    # File still cleaned up
    assert client.files.deleted == ["file_123"]


async def test_extract_image_passes_data_url_directly() -> None:
    fake_response = _FakeOcrResponse(pages=[_FakeOcrPage(markdown="image text")])
    client = _FakeMistralClient(fake_response)
    plugin = MistralOcr(client=client)  # type: ignore[arg-type]

    result = await plugin.extract(b"\xff\xd8 fake jpeg", "image/jpeg")

    # No upload for images — passed inline as a data URL
    assert client.files.uploaded == []
    assert client.files.deleted == []
    last = client.ocr.last_call
    assert last is not None
    assert last["document"]["type"] == "image_url"
    assert last["document"]["image_url"].startswith("data:image/jpeg;base64,")
    assert "image text" in result.markdown


async def test_extract_dedupes_repeated_image_ids() -> None:
    """Same img-0 returned on multiple pages → emitted once."""
    img = _FakeOcrImage("img-shared.png", "image/png", _PNG)
    fake_response = _FakeOcrResponse(
        pages=[
            _FakeOcrPage(markdown="![img-shared.png](img-shared.png)", images=[img]),
            _FakeOcrPage(markdown="![img-shared.png](img-shared.png)", images=[img]),
        ]
    )
    client = _FakeMistralClient(fake_response)
    plugin = MistralOcr(client=client)  # type: ignore[arg-type]
    result = await plugin.extract(b"%PDF stub", "application/pdf")
    assert len(result.images) == 1


async def test_extract_unsupported_content_type_raises() -> None:
    plugin = MistralOcr(client=_FakeMistralClient(_FakeOcrResponse([])))  # type: ignore[arg-type]
    with pytest.raises(OcrUnavailable, match="unsupported content type"):
        await plugin.extract(b"text", "text/plain")


async def test_extract_skips_image_with_bad_data_url() -> None:
    """A garbled data URL is logged and skipped, doesn't kill the run."""

    class _BadImage:
        id = "img-bad.png"
        image_base64 = "not-a-data-url-at-all"

    fake_response = _FakeOcrResponse(
        pages=[_FakeOcrPage(markdown="text", images=[_BadImage()])]  # type: ignore[list-item]
    )
    client = _FakeMistralClient(fake_response)
    plugin = MistralOcr(client=client)  # type: ignore[arg-type]
    result = await plugin.extract(b"%PDF stub", "application/pdf")
    assert result.images == []  # bad image silently skipped
    assert "text" in result.markdown
