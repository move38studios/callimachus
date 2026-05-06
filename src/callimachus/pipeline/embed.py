"""Embed stage — local sentence-transformers + nomic-embed-text-v1.5.

The `Embedder` Protocol has two methods:
- `embed_documents(texts)` — for indexed chunks (uses `search_document:` prefix)
- `embed_query(text)` — for retrieval queries (uses `search_query:` prefix)

The prefix is **mandatory** per nomic's model card — skipping it costs
~5 MTEB points. Output is 768-d float32 packed for sqlite-vec.

`apply_contextual_prefix` is the cheap "Contextual Retrieval lite"
helper: prepend `[Paper: title] [Section: section]\\n\\n` to a chunk
before embedding. Captures most of the Anthropic Contextual Retrieval
gain at zero LLM cost.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

log = logging.getLogger(__name__)

DEFAULT_MODEL_ID = "nomic-ai/nomic-embed-text-v1.5"
EMBEDDING_DIM = 768

DOCUMENT_PREFIX = "search_document: "
QUERY_PREFIX = "search_query: "


@runtime_checkable
class Embedder(Protocol):
    """Embed text → 768-d vectors. One Protocol, two methods."""

    name: str

    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    async def embed_query(self, text: str) -> list[float]: ...


def apply_contextual_prefix(
    text: str, *, title: str | None = None, section: str | None = None
) -> str:
    """Prepend `[Paper: title] [Section: section]\\n\\n` if either is non-empty.

    Cheap "Contextual Retrieval lite" — improves retrieval quality with
    zero LLM cost. Result: `text` if both are empty, else prefix + text.
    """
    parts: list[str] = []
    if title:
        parts.append(f"[Paper: {title}]")
    if section:
        parts.append(f"[Section: {section}]")
    if not parts:
        return text
    return " ".join(parts) + "\n\n" + text


class NomicEmbedder:
    """Default Embedder — local nomic-embed-text-v1.5 via sentence-transformers."""

    name: str = "nomic-embed-text-v1.5"

    def __init__(
        self,
        *,
        model: SentenceTransformer | None = None,
        model_id: str = DEFAULT_MODEL_ID,
        device: str | None = None,
    ) -> None:
        """Construct a NomicEmbedder.

        Args:
            model: Pre-loaded SentenceTransformer (for tests / sharing).
                If None, the model is lazily loaded on first use.
            model_id: HuggingFace model id; defaults to nomic-embed-text-v1.5.
            device: 'cpu', 'cuda', 'mps', or None to autodetect.
        """
        self._model = model
        self._model_id = model_id
        self._device = device

    def _model_or_load(self) -> SentenceTransformer:
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            log.info("loading embedding model %s (first call may take a moment)", self._model_id)
            self._model = SentenceTransformer(
                self._model_id,
                trust_remote_code=True,
                device=self._device,
            )
        return self._model

    def _encode_sync(self, texts: list[str]) -> list[list[float]]:
        model = self._model_or_load()
        # `convert_to_numpy=True` returns ndarray of shape (n, dim)
        arr: Any = model.encode(texts, convert_to_numpy=True, show_progress_bar=False)  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        return [list(row) for row in arr]

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        prefixed = [DOCUMENT_PREFIX + t for t in texts]
        return await asyncio.to_thread(self._encode_sync, prefixed)

    async def embed_query(self, text: str) -> list[float]:
        prefixed = QUERY_PREFIX + text
        result = await asyncio.to_thread(self._encode_sync, [prefixed])
        return result[0]
