"""Tests for the embed module."""

from __future__ import annotations

import pytest

from callimachus.pipeline.embed import (
    DOCUMENT_PREFIX,
    EMBEDDING_DIM,
    QUERY_PREFIX,
    Embedder,
    NomicEmbedder,
    apply_contextual_prefix,
)

# ---------- contextual prefix ----------


def test_apply_contextual_prefix_full() -> None:
    text = "the body content"
    out = apply_contextual_prefix(text, title="DDPM", section="Introduction")
    assert out.startswith("[Paper: DDPM] [Section: Introduction]\n\n")
    assert out.endswith("the body content")


def test_apply_contextual_prefix_title_only() -> None:
    out = apply_contextual_prefix("body", title="X", section=None)
    assert out == "[Paper: X]\n\nbody"


def test_apply_contextual_prefix_section_only() -> None:
    out = apply_contextual_prefix("body", title=None, section="Method")
    assert out == "[Section: Method]\n\nbody"


def test_apply_contextual_prefix_neither() -> None:
    """No prefix applied when both are empty/None — text returned unchanged."""
    assert apply_contextual_prefix("body", title=None, section=None) == "body"
    assert apply_contextual_prefix("body", title="", section="") == "body"


# ---------- Embedder Protocol shape ----------


def test_nomic_embedder_satisfies_embedder_protocol() -> None:
    """NomicEmbedder structurally satisfies the Embedder Protocol."""
    embedder = NomicEmbedder()
    assert isinstance(embedder, Embedder)
    assert embedder.name == "nomic-embed-text-v1.5"


# ---------- prefix application via mocked encode ----------


class _FakeSentenceTransformer:
    """Stand-in for sentence_transformers.SentenceTransformer."""

    def __init__(self) -> None:
        self.encode_calls: list[list[str]] = []

    def encode(
        self,
        texts: list[str],
        *,
        convert_to_numpy: bool = True,
        show_progress_bar: bool = False,
    ) -> list[list[float]]:
        del convert_to_numpy, show_progress_bar
        self.encode_calls.append(list(texts))
        # Return one canned 768-d vector per text (a numpy-like list of lists is fine
        # for our `list(row) for row in arr` extraction).
        return [[0.1] * EMBEDDING_DIM for _ in texts]


async def test_embed_documents_applies_search_document_prefix() -> None:
    fake = _FakeSentenceTransformer()
    embedder = NomicEmbedder(model=fake)  # type: ignore[arg-type]

    result = await embedder.embed_documents(["hello", "world"])

    assert len(result) == 2
    assert all(len(v) == EMBEDDING_DIM for v in result)
    assert fake.encode_calls == [[DOCUMENT_PREFIX + "hello", DOCUMENT_PREFIX + "world"]]


async def test_embed_query_applies_search_query_prefix() -> None:
    fake = _FakeSentenceTransformer()
    embedder = NomicEmbedder(model=fake)  # type: ignore[arg-type]

    result = await embedder.embed_query("what is this paper about")

    assert len(result) == EMBEDDING_DIM
    assert fake.encode_calls == [[QUERY_PREFIX + "what is this paper about"]]


async def test_embed_documents_empty_list_skips_model_call() -> None:
    fake = _FakeSentenceTransformer()
    embedder = NomicEmbedder(model=fake)  # type: ignore[arg-type]

    result = await embedder.embed_documents([])
    assert result == []
    assert fake.encode_calls == []


# ---------- live test (real model load — gated) ----------


@pytest.mark.live
async def test_live_nomic_embeds_three_documents() -> None:
    """Actually load nomic-v1.5 and embed 3 chunks. Skipped in default CI."""
    embedder = NomicEmbedder()
    docs = ["A diffusion model generates images.", "BM25 is a ranking function."]
    embeddings = await embedder.embed_documents(docs)
    assert len(embeddings) == 2
    assert all(len(e) == EMBEDDING_DIM for e in embeddings)
    # Check vectors aren't all zeros (basic sanity)
    assert any(v != 0.0 for v in embeddings[0])
