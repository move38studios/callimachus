"""Mistral OCR — bundled `OcrProvider` implementation.

Uses `mistralai`'s sync SDK wrapped with `asyncio.to_thread` since our
pipeline is async. Upload flow per the official cookbook:

    files.upload(purpose="ocr") → files.get_signed_url() → ocr.process()
    → files.delete()  (cleanup)

Images come back as base64 data URLs (`data:image/jpeg;base64,...`) on
each `page.images[i].image_base64` — we parse them into bytes here, so
the caller writes plain image files to disk and rewrites markdown
references.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import re
from typing import Any

from mistralai.client import Mistral

from callimachus.pipeline.ocr.protocols import (
    OcrImage,
    OcrResult,
    OcrUnavailable,
)

log = logging.getLogger(__name__)

DEFAULT_MODEL = "mistral-ocr-latest"

# Match a data URL: "data:image/jpeg;base64,<base64-payload>"
_DATA_URL_RE = re.compile(r"^data:([^;,]+);base64,(.*)$", re.DOTALL)


def parse_data_url(data_url: str) -> tuple[str, bytes]:
    """Return (content_type, bytes) from a data URL string.

    Raises ValueError if the input isn't a valid base64 data URL.
    """
    match = _DATA_URL_RE.match(data_url)
    if not match:
        raise ValueError(f"not a base64 data URL (first 60 chars: {data_url[:60]!r})")
    content_type = match.group(1).strip().lower()
    payload = match.group(2)
    try:
        return content_type, base64.b64decode(payload)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"failed to decode base64: {exc}") from exc


class MistralOcr:
    """`OcrProvider` backed by Mistral's `mistral-ocr-latest` model."""

    name: str = "mistral"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = DEFAULT_MODEL,
        client: Mistral | None = None,
    ) -> None:
        """Construct a Mistral OCR provider.

        Args:
            api_key: Mistral API key. Defaults to `$MISTRAL_API_KEY`.
            model: OCR model name. Defaults to `mistral-ocr-latest`.
            client: Pre-built Mistral client (for tests / custom configuration).
                If None, a client is created lazily on first use.
        """
        self._api_key = api_key or os.environ.get("MISTRAL_API_KEY")
        self._model = model
        self._client = client

    def _client_or_init(self) -> Mistral:
        if self._client is None:
            if not self._api_key:
                raise OcrUnavailable(
                    "MistralOcr: no API key (set MISTRAL_API_KEY or pass api_key=...)"
                )
            self._client = Mistral(api_key=self._api_key)
        return self._client

    async def extract(self, artifact_bytes: bytes, content_type: str) -> OcrResult:
        """Run Mistral OCR on the given artifact, return markdown + images.

        For PDFs: upload → signed URL → ocr.process(document_url=...).
        For images: pass directly as a data URL.

        Cleans up any uploaded file on success or failure.
        """
        client = self._client_or_init()
        main_ct = content_type.split(";", 1)[0].strip().lower()

        try:
            if main_ct == "application/pdf":
                return await asyncio.to_thread(self._extract_pdf_sync, client, artifact_bytes)
            if main_ct.startswith("image/"):
                return await asyncio.to_thread(
                    self._extract_image_sync, client, artifact_bytes, main_ct
                )
        except OcrUnavailable:
            raise
        except Exception as exc:
            raise OcrUnavailable(f"MistralOcr: {type(exc).__name__}: {exc}") from exc

        raise OcrUnavailable(f"MistralOcr: unsupported content type {content_type!r}")

    # ----- sync internals (run via asyncio.to_thread) -----

    def _extract_pdf_sync(self, client: Mistral, pdf_bytes: bytes) -> OcrResult:
        """Upload PDF, get signed URL, run OCR, clean up.

        `content` is raw bytes, not io.BytesIO — Mistral SDK 2.x's pydantic
        validator on `file.content` accepts `bytes | IO | BufferedReader`,
        but rejects `io.BytesIO` even though it's a valid IO subclass
        (typing.IO doesn't pass `isinstance` checks reliably). Raw bytes
        is the unambiguous path.
        """
        uploaded = client.files.upload(  # pyright: ignore[reportUnknownMemberType]
            file={
                "file_name": "callimachus_doc.pdf",
                "content": pdf_bytes,
            },
            purpose="ocr",
        )
        file_id: str = uploaded.id
        try:
            signed = client.files.get_signed_url(file_id=file_id)  # pyright: ignore[reportUnknownMemberType]
            url: str = signed.url
            response = client.ocr.process(  # pyright: ignore[reportUnknownMemberType]
                model=self._model,
                document={"type": "document_url", "document_url": url},
                include_image_base64=True,
            )
            return self._response_to_result(response)
        finally:
            try:
                client.files.delete(file_id=file_id)  # pyright: ignore[reportUnknownMemberType]
            except Exception as exc:
                log.warning("MistralOcr: file cleanup failed for %s: %s", file_id, exc)

    def _extract_image_sync(
        self, client: Mistral, image_bytes: bytes, content_type: str
    ) -> OcrResult:
        """Pass an image directly as a data URL — no upload needed."""
        b64 = base64.b64encode(image_bytes).decode("ascii")
        data_url = f"data:{content_type};base64,{b64}"
        response = client.ocr.process(  # pyright: ignore[reportUnknownMemberType]
            model=self._model,
            document={"type": "image_url", "image_url": data_url},
            include_image_base64=True,
        )
        return self._response_to_result(response)

    def _response_to_result(self, response: Any) -> OcrResult:
        """Convert a Mistral OCR response into our `OcrResult`."""
        pages = list(getattr(response, "pages", []) or [])
        markdown_parts: list[str] = []
        images: list[OcrImage] = []
        seen_ids: set[str] = set()

        for page in pages:
            page_md = getattr(page, "markdown", "") or ""
            markdown_parts.append(page_md)
            for img in getattr(page, "images", []) or []:
                img_id = getattr(img, "id", None)
                data_url = getattr(img, "image_base64", None)
                if not img_id or not data_url:
                    continue
                if img_id in seen_ids:
                    continue
                try:
                    content_type, raw_bytes = parse_data_url(data_url)
                except ValueError as exc:
                    log.warning(
                        "MistralOcr: skipping image %r — bad data URL: %s",
                        img_id,
                        exc,
                    )
                    continue
                images.append(OcrImage(id=img_id, bytes_=raw_bytes, content_type=content_type))
                seen_ids.add(img_id)

        return OcrResult(
            markdown="\n\n".join(markdown_parts).strip() + "\n",
            images=images,
            pages=len(pages),
            provider=self.name,
        )
