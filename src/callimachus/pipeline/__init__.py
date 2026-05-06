"""Pipeline modules — the deterministic stages that turn a candidate into an indexed work.

Stages (in order, each idempotent + checkpointable):
    resolve   → ResolvedFile from registry  (just delegates to registry.resolve)
    download  → bytes written to library/works/{slug}/original.{ext}
    extract   → markdown written to library/works/{slug}/paper.md
    enrich    → metadata via LLM call (M1.3c)
    embed     → chunks + embeddings (M1.3d)
    index     → DB rows for Work + Chunk + vec_chunks (M1.3d)
"""
