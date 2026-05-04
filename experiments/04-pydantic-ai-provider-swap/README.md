# 04 — pydantic-ai-provider-swap

Run the same judge schema across multiple model families via OpenRouter, with one key. Validates the multi-provider promise and tests how different models handle structured output (especially the Gemini caveat from experiment 03).

## What we're testing

- That swapping models is a **one-line change** (model string) — no other code changes
- That the same `Verdict` schema validates across model families
- Whether Gemini actually trips the "tools + structured output" issue in practice when routed through OpenRouter
- Latency and token-cost differences across models — informs default model choices for each agent role
- Whether smaller / cheaper models produce reasonable verdicts (could a Llama or Haiku-class model do the workhorse judging?)

## The setup

Same fixture as experiment 03: judge the Ho 2020 DDPM abstract against "diffusion models for image generation" with the same `Verdict` schema. Run it through a list of candidate models. Report per-model: success/error, verdict, latency, tokens.

## Run

```bash
uv run experiments/04-pydantic-ai-provider-swap/run.py
```

Outputs a comparison table at the end so we can see at a glance how model families compare.

## Success criteria

- At least Anthropic + OpenAI + Llama (open weights) routes return valid verdicts
- Verdicts are broadly consistent (all judging the DDPM paper as a strong candidate, even if scores vary)
- Any structured-output failures are clearly attributed to the model/provider that caused them (not silently swallowed)
