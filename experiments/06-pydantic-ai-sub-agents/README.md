# 06 — pydantic-ai-sub-agents

Orchestrator agent spawns hunter sub-agents. Validates the architecture all of agentic discovery depends on: one coordinator at the top, multiple specialised workers in parallel underneath, results bubble back up.

## What we're testing

Two complementary patterns Pydantic AI supports:

### Demo A — orchestrator-driven delegation (`@agent.tool` calls another agent)

The orchestrator has a `spawn_hunter(angle, brief)` tool. The model itself decides — based on the user's request — what angles to pursue and spawns a sub-agent per angle. Pydantic AI's recommended "agent delegation" pattern, with usage tracking threaded through `RunContext`.

This is what the orchestrator agent will actually use in production.

### Demo B — explicit parallel execution (`asyncio.gather`)

Skip the orchestrator agent entirely; just dispatch N hunter agents in parallel from plain Python. Faster, more deterministic, less LLM token cost — appropriate when *we* (not the model) decide how many hunters to spawn and on what angles.

This is what the discovery loop will use after the orchestrator has finished planning.

Both should work. We need to know the shape of each.

## What we want to learn

- Does usage tracking thread cleanly from sub-agent up to parent?
- Are sub-agent messages kept separate from the parent's message history?
- Does the parallel pattern actually parallelize (latency ≈ slowest hunter, not sum)?
- How does the orchestrator decide how many hunters to spawn? Does it match what we'd want for real research planning?
- Token cost of orchestrator-driven coordination vs explicit parallel
- Any surprises with sub-agent error handling (does a hunter failure crash the orchestrator?)

## Run

```bash
uv run experiments/06-pydantic-ai-sub-agents/run.py
```

Runs both demos in sequence. Outputs comparison at the end.

## Success criteria

- Orchestrator (Demo A) spawns at least 2 hunters and synthesises their results into a coherent answer
- Parallel hunters (Demo B) all return structured `HunterReport` instances
- Demo B's elapsed time ≈ slowest individual hunter (proves parallelism)
- Total usage from Demo A includes sub-agent tokens (proves usage threading)
