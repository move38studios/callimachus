"""Ceremony — interactive HITL conversion of an AngleTree into a Plan.

The product-defining UX moment in M2: the scout finishes, the user sees
what was found, and we ask a small number of high-impact questions before
the deep build commits. The result is a `Plan` that gets persisted as YAML
for the user to review/edit and then run with `calli build --from-plan`.

Prompter is a Protocol so tests can plug in a deterministic answer queue
without monkeypatching `input()` globally.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal, Protocol

from callimachus.discovery.plan import Angle, AngleTree, Plan, slugify
from callimachus.discovery.scout import render_angle_tree

log = logging.getLogger(__name__)

DEFAULT_MAX_WORKS = 50

_VALID_ORIENTATIONS: tuple[str, ...] = ("foundations", "recent", "both")


class Prompter(Protocol):
    """Anything that can ask the user a question and return the answer."""

    def ask(self, question: str, default: str | None = None) -> str: ...

    def display(self, text: str) -> None: ...


@dataclass
class CliPrompter:
    """Default Prompter wired to stdin/stdout via builtins.

    Kept dataclass-shaped (no Rich, no prompt_toolkit) so tests don't need
    to mock heavy machinery. M2.5 may swap this for a Rich-backed version.
    """

    def ask(self, question: str, default: str | None = None) -> str:
        prompt = f"{question} [default: {default}] " if default else f"{question} "
        try:
            answer = input(prompt).strip()
        except EOFError:
            answer = ""
        return answer if answer else (default or "")

    def display(self, text: str) -> None:
        print(text)  # noqa: T201


@dataclass
class QueuedPrompter:
    """Test prompter: returns answers from a pre-built list, captures display output."""

    answers: list[str]
    display_log: list[str]

    def __init__(self, answers: list[str]) -> None:
        self.answers = list(answers)
        self.display_log = []

    def ask(self, question: str, default: str | None = None) -> str:
        del question
        if not self.answers:
            return default or ""
        return self.answers.pop(0)

    def display(self, text: str) -> None:
        self.display_log.append(text)


# ---------- parsing helpers ----------


def parse_angle_selection(answer: str, *, available: int) -> list[int]:
    """Turn '1, 3, 5' or 'all' or '' into a list of 0-indexed angle positions.

    - 'all' or empty → all indices
    - '1,3,5' → [0, 2, 4]
    - Out-of-range entries are silently dropped (with a debug log)
    """
    answer = answer.strip().lower()
    if not answer or answer == "all":
        return list(range(available))

    out: list[int] = []
    seen: set[int] = set()
    for part in answer.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            n = int(part)
        except ValueError:
            log.debug("ceremony: ignoring non-numeric token %r in selection", part)
            continue
        idx = n - 1
        if 0 <= idx < available and idx not in seen:
            out.append(idx)
            seen.add(idx)

    return out if out else list(range(available))


def parse_keywords(answer: str) -> list[str]:
    """Split a free-text answer on commas/semicolons into deduped keywords."""
    if not answer.strip():
        return []
    raw = [p.strip() for p in answer.replace(";", ",").split(",")]
    out: list[str] = []
    seen: set[str] = set()
    for term in raw:
        if term and term.lower() not in seen:
            out.append(term)
            seen.add(term.lower())
    return out


def parse_orientation(answer: str) -> Literal["foundations", "recent", "both"]:
    """'foundations', 'recent', 'both' (default). Loose matching on prefix."""
    a = answer.strip().lower()
    if not a:
        return "both"
    for option in _VALID_ORIENTATIONS:
        if option.startswith(a):
            return option  # type: ignore[return-value]
    return "both"


def parse_max_works(answer: str, *, default: int = DEFAULT_MAX_WORKS) -> int:
    """Positive int, or default on parse failure / empty."""
    a = answer.strip()
    if not a:
        return default
    try:
        n = int(a)
    except ValueError:
        return default
    return max(1, n)


# ---------- the ceremony itself ----------


def auto_plan(tree: AngleTree, *, max_works: int = DEFAULT_MAX_WORKS) -> Plan:
    """No-questions-asked plan. All angles, both orientations, no anchors."""
    return Plan(
        topic=tree.topic,
        slug=slugify(tree.topic),
        angles=list(tree.angles),
        extra_keywords=[],
        orientation="both",
        max_works=max_works,
        discovery=tree,
    )


def run_ceremony(
    tree: AngleTree,
    *,
    prompter: Prompter | None = None,
    auto: bool = False,
    max_works_default: int = DEFAULT_MAX_WORKS,
) -> Plan:
    """Walk the user from an AngleTree → Plan.

    With `auto=True`, no prompts are issued and `auto_plan()` is returned.
    """
    if auto:
        return auto_plan(tree, max_works=max_works_default)

    if prompter is None:
        prompter = CliPrompter()

    prompter.display(render_angle_tree(tree))

    raw_selection = prompter.ask(
        "Which angles matter most? Comma-separated numbers, or 'all'",
        default="all",
    )
    indices = parse_angle_selection(raw_selection, available=len(tree.angles))
    selected: list[Angle] = [tree.angles[i] for i in indices]

    raw_keywords = prompter.ask(
        "Any specific authors, papers, or keywords to anchor on? (comma-separated, "
        "or blank for none)",
        default="",
    )
    extra_keywords = parse_keywords(raw_keywords)

    raw_orientation = prompter.ask(
        "Orientation — 'foundations', 'recent', or 'both'?",
        default="both",
    )
    orientation = parse_orientation(raw_orientation)

    raw_max = prompter.ask(
        "Hard cap on works to ingest?",
        default=str(max_works_default),
    )
    max_works = parse_max_works(raw_max, default=max_works_default)

    return Plan(
        topic=tree.topic,
        slug=slugify(tree.topic),
        angles=selected,
        extra_keywords=extra_keywords,
        orientation=orientation,
        max_works=max_works,
        discovery=tree,
    )
