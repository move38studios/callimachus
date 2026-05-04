# 03 — pydantic-ai-structured-output — LEARNINGS

## Run log

- **2026-05-04**, macOS, `openrouter:anthropic/claude-sonnet-4.6`.
  - Judged the Ho 2020 DDPM abstract against "diffusion models for image generation" with the `Verdict` schema.
  - Result: valid `Verdict` instance returned. relevance=10, seminality=10, accept=True, snowball_candidate=True, well-reasoned multi-sentence reasoning. concerns=[].
  - Single request (no validation retry). 1357 input + 267 output = 1624 tokens.
  - All type checks passed: `isinstance(verdict, Verdict)`, `int`/`bool`/`list` types preserved on the parsed instance.

## Findings

### Mechanism — how Pydantic AI gets structured output

The framework uses **Tool Output mode by default**: the schema becomes a synthetic tool called `final_result`, and the model "calls" that tool with the structured response as args. Visible in the message history:

```
[ModelResponse]
    ToolCallPart: ToolCallPart(tool_name='final_result', args='{"relevance": 10, ...}')
[ModelRequest]
    ToolReturnPart: Final result processed.
```

This is significant because it means **structured output is just regular tool calling under the hood** — and we already proved that works rock-solid in experiment 02.

### Reliability with OpenRouter — known concern resolved

Pydantic AI documents three output modes:

| Mode | How it works | Compatibility |
| --- | --- | --- |
| **Tool Output** (default) | Schema → synthetic tool → model calls it | "Works with virtually all models" |
| **Native Output** | Provider's native structured-output API | Not supported by all models |
| **Prompted Output** | Schema injected in prompt; model emits JSON text | Universal |

Earlier reports of structured-output issues on OpenRouter were typically about Native Output mode — some upstream providers don't expose JSON-mode reliably through OpenRouter's proxy. The Tool Output default sidesteps this entirely: OpenRouter relays tool calls cleanly, so structured output is as reliable as tool calling.

**Documented caveat**: Gemini can't use tools and structured output simultaneously (per Pydantic AI's docs). If we ever route the judge through Gemini, we'd need to switch that path to `NativeOutput` or `PromptedOutput`.

### Schema → model interface

- `Field(ge=0, le=10, description=...)` constraints flow through to the schema the model sees.
- Field descriptions are read by the model — they function like inline prompts. Treat them as part of the prompt design.
- `min_length`, `default_factory`, etc. work as expected.
- The model respected all constraints in our run; would only retry if validation failed.

### Cost shape

- ~1.6k tokens for one judge call. At Sonnet 4.6 OpenRouter pricing, this is well under $0.01.
- Implication: judging 500 candidates costs roughly $4–8. Matches the DEV_PLAN cost estimates.
- The schema overhead per judge call is fixed (~few hundred tokens for the schema + system prompt); the variable part is the abstract.

### Quality of judgment

The Sonnet 4.6 verdict on the DDPM paper was strong: it identified the work as a landmark, picked up on the "VAE/energy-model lineage" preference from the collection notes, and reasoned about why it merited admission and snowball-seeding. This is encouraging for the judge use case — the model can clearly handle nuanced relevance scoring with good rubric prompting.

## Decisions

- **Use Tool Output mode (the default) for the judge.** Don't override unless we hit a specific provider that needs it.
- **Provider-mode awareness lives in the LLMProvider abstraction** (per `ARCHITECTURE.md`): if/when we add Gemini, the wrapper should auto-select `NativeOutput` mode for it.
- **Field descriptions are part of the prompt.** Treat them with the same care as system prompt wording. Future judge schema iterations should review descriptions when tuning behaviour.
- **Judge schema is roughly the right shape**: relevance + seminality + accept + snowball_candidate + reasoning + concerns. Refinement pending real-corpus testing in M2/M3, but the structure works.

## Open questions

- What happens when the abstract is hostile (irrelevant noise, non-academic blog post, gibberish)? Need to test edge cases before relying on the judge.
- How does judgment quality drop on smaller/cheaper models? Run the same fixture through Haiku and a smaller open model to see — informs the per-task model defaults.
- Does adding citation contexts to the prompt (the seminality unlock from `ARCHITECTURE.md`) materially change verdicts? Test in M2.
- Should we include the model's own confidence as a field (`uncertainty: int`)? Or trust `concerns` to surface uncertainty? Lean toward `concerns` — fewer fields, less to game.
