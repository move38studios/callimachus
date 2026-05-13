"""Discovery agents — scout, hunter, judge, orchestrator.

These are the M2 agents responsible for going from a topic to a library:

- **scout** (M2.3) — shallow-probe a topic, return an angle tree
- **judge** (M2.1, this milestone) — single LLM call: accept/reject a candidate
- **hunter** (M2.2) — sub-agent that runs an angle, ranking candidates
- **orchestrator** (M2.4) — runs hunters in parallel, hands accepted candidates to ingest

The judge lives here (not in `pipeline/`) because admission is a discovery-time
decision: it gates whether a candidate even enters the pipeline.
"""
