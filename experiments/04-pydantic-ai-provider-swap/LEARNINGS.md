# 04 — pydantic-ai-provider-swap — LEARNINGS

## Run log

- **2026-05-04**, macOS. Same fixture (Ho 2020 DDPM) and `Verdict` schema as experiment 03, swapped across 5 models via OpenRouter.

| Model | OK | rel | sem | acc | snow | latency | tokens |
| --- | :-: | :-: | :-: | :-: | :-: | --- | --- |
| Claude Sonnet 4.6 | ✓ | 10 | 10 | Y | Y | 5.6s | 1482 |
| Claude Haiku 4.5 | ✓ | 10 | 10 | Y | Y | 21.9s | 1472 |
| GPT-5.1 | ✓ | 10 | 10 | Y | Y | 3.7s | 709 |
| Gemini 2.5 Pro | ✓ | 10 | 10 | Y | Y | 12.8s | 1633 |
| Llama 3.3 70B | ✓ | 9 | 8 | Y | Y | 12.8s | 1180 |

5/5 models returned valid `Verdict` instances. Provider swap is a one-line change as advertised.

## Findings

### The swap really is one line

`Agent("openrouter:openai/gpt-5.1", output_type=Verdict, ...)` and `Agent("openrouter:google/gemini-2.5-pro", output_type=Verdict, ...)` are drop-in replacements. The rest of the code is identical: same prompt, same tool decorators (n/a here), same usage API. Pydantic AI's promise holds.

### Gemini caveat — needs re-evaluation

Experiment 03's LEARNINGS captured a documented caveat: "Gemini can't combine tools + structured output." But **Gemini 2.5 Pro returned a valid verdict here without any special handling**. Three possible explanations (we don't know which yet):

1. Pydantic AI auto-detects Gemini and silently switches to `NativeOutput` mode internally.
2. The caveat applies to older Gemini versions; 2.5 Pro supports tools + structured output natively.
3. Going through OpenRouter normalises requests enough that the underlying issue doesn't manifest.

**Action**: don't bake the Gemini-must-use-NativeOutput logic into the LLMProvider abstraction yet. Soften the `ARCHITECTURE.md` claim. Add this to open questions; revisit when we have a real reason to use Gemini for the judge.

### Verdict consistency across families

All four frontier models (Sonnet 4.6, Haiku 4.5, GPT-5.1, Gemini 2.5 Pro) scored DDPM at 10/10/accept/snowball. Llama 3.3 70B was slightly more conservative at 9/8 but still accepted and snowballed. This suggests the judge is robust to model choice — we won't get wildly different libraries because of which model we picked. Good for portability.

### Concern surfacing varies by model

Only **GPT-5.1** populated the `concerns` field, with three useful ones (e.g. "focuses mainly on pixel-space diffusion, not later latent diffusion variants"). Sonnet, Haiku, Gemini, and Llama all returned empty `concerns`. Two readings:

- GPT models are biased toward critique by training/RLHF.
- Other models read the abstract as fully positive and didn't manufacture concerns.

Implication: if `concerns` is meant to capture genuine uncertainty, model choice matters. We may want to either (a) prompt more explicitly for concerns, or (b) treat empty concerns as "no information" rather than "no concerns."

### Latency

- GPT-5.1 was fastest (3.7s) — plausibly the synchronous path through OpenAI.
- Sonnet 4.6 second (5.6s).
- Gemini and Llama in the middle (~12.8s each).
- **Haiku 4.5 was surprisingly slow at 21.9s** — expected to be the fastest. Possible explanations: cold start on OpenRouter routing, secondary routing path, capacity issue at the time of the run. Worth a re-run on a different day before drawing conclusions.

### Token cost shape

GPT-5.1 used **476 input tokens** vs ~1200 for the Anthropic models on the same prompt. OpenAI must encode the system prompt + schema differently (or OpenRouter rewrites it). For high-volume judging this matters: on token-priced models, GPT-5.1 might be 30–60% cheaper per call at the same quality.

### Output verbosity varies

Gemini emitted 1219 output tokens for the verdict — much more than others (200–270). Mostly in the `reasoning` field. Verbose model. If we route to Gemini we may want to add a `max_tokens` cap to control cost, or instruct in the system prompt for brevity.

## Decisions

- **Default workhorse judge**: Sonnet 4.6 (good balance of speed, quality, and consistency with the rest of our pipeline).
- **Cheap-mode judge** (for users wanting low cost): Llama 3.3 70B via OpenRouter (open weights, scores reasonable, slightly more conservative). Re-test Haiku 4.5 latency before defaulting to it.
- **Synthesis pass** (final overview): Opus 4.7 — to be tested in a later experiment.
- **Don't pre-emptively code around Gemini's documented caveat.** Let it run with default Tool Output mode unless we see real failures.
- **Soften `ARCHITECTURE.md` claim** about Gemini needing special handling.

## Open questions

- Does Pydantic AI silently switch modes for Gemini, or does Gemini 2.5 actually support tools + structured output? (Investigate when/if we have reason to make this matter.)
- Re-run Haiku 4.5 on a different day — is the 21.9s consistent or a one-off?
- Does the GPT vs Anthropic input-token gap persist on longer prompts (e.g. when we include citation contexts)? Worth measuring at M2.
- Concern-surfacing: prompt-engineer for it explicitly, or accept that some models won't surface concerns and treat empty as unknown?
- For "free-tier" / "hobbyist" usage: what's the cheapest model that produces acceptable judgments? (Run a cost-vs-quality bake-off on a 50-paper sample later.)
