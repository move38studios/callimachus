"""OCR providers — turn artifact bytes (PDFs, images) into markdown + extracted images.

Pluggable via the `OcrProvider` Protocol. Bundled: `MistralOcr`. Future:
Claude vision, Marker, community providers.
"""

from __future__ import annotations

from callimachus.pipeline.ocr.mistral import MistralOcr
from callimachus.pipeline.ocr.protocols import (
    OcrImage,
    OcrProvider,
    OcrResult,
    OcrUnavailable,
)

__all__ = [
    "MistralOcr",
    "OcrImage",
    "OcrProvider",
    "OcrResult",
    "OcrUnavailable",
]
