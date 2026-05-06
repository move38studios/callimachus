"""OCR provider contract — Protocol + result types + recoverable exception."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field


class OcrImage(BaseModel):
    """One image extracted from an artifact (figure, chart, photograph)."""

    id: str = Field(
        description="The image's identifier — also the filename used in markdown "
        "placeholders, e.g. 'img-0.jpeg'."
    )
    bytes_: bytes
    content_type: str = Field(description="e.g. 'image/jpeg', 'image/png'.")


class OcrResult(BaseModel):
    """The output of an OCR run over a single document."""

    markdown: str = Field(
        description="Combined markdown across all pages. Image placeholders "
        "still reference image ids verbatim — the caller rewrites them when "
        "saving images to the library on disk."
    )
    images: list[OcrImage] = Field(default_factory=lambda: [])
    pages: int = Field(description="Number of pages in the input.")
    provider: str = Field(description="Plugin name that produced this result.")


class OcrUnavailable(Exception):  # noqa: N818
    """Recoverable OCR failure: rate-limited, API down, transient parse error.

    Mirrors `callimachus.sources.SourceUnavailable` — caught at the agent
    boundary and translated to `pydantic_ai.ModelRetry`.
    """


@runtime_checkable
class OcrProvider(Protocol):
    """Turn artifact bytes (PDF, image) into markdown + extracted images."""

    name: str

    async def extract(self, artifact_bytes: bytes, content_type: str) -> OcrResult: ...
