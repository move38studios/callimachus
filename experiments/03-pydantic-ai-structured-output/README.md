# 03 — pydantic-ai-structured-output

Get a typed Pydantic model out of an agent — the prototype for the **judge** that scores every candidate work in the discovery loop.

## What we're testing

- Declaring an `output_type` on `Agent[..., OutputModel]`
- Whether the LLM reliably returns a valid Pydantic instance (no JSON wrangling)
- Behaviour when the model produces invalid output (constraint violations, missing fields)
- Whether Pydantic AI auto-retries on validation errors
- Token cost compared to free-text output
- Whether nested structures (`list[str]`, enums) come through cleanly

## The schema (judge prototype)

```python
class Verdict(BaseModel):
    relevance: int                    # 0–10
    seminality: int                   # 0–10
    accept: bool
    snowball_candidate: bool          # would seed further hunting
    reasoning: str
    concerns: list[str]               # things that lowered the score
```

Field constraints (`Field(ge=0, le=10)`) test what happens when the model hallucinates an out-of-range score.

## Run

```bash
uv run experiments/03-pydantic-ai-structured-output/run.py
```

Default behaviour: judges a fixture abstract (Ho 2020 DDPM) against a stub topic ("diffusion models for image generation"). Optionally pass `--bad-prompt` to give the model an unreasonable task and see if/how it produces invalid output that triggers a retry.

## Success criteria

- Returns a valid `Verdict` instance with all fields populated
- Field types match (e.g. `result.output.relevance` is an `int`, not a string)
- `result.output.reasoning` is non-trivial (real reasoning, not "ok")
- We see the message history and can identify retries if they happened
