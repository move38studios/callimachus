"""Tests for the ceremony — HITL conversion of AngleTree → Plan."""

from __future__ import annotations

import pytest

from callimachus.discovery.ceremony import (
    DEFAULT_MAX_WORKS,
    QueuedPrompter,
    auto_plan,
    parse_angle_selection,
    parse_keywords,
    parse_max_works,
    parse_orientation,
    run_ceremony,
)
from callimachus.discovery.plan import Angle, AngleTree

# ---------- parsers ----------


@pytest.mark.parametrize(
    "answer, available, expected",
    [
        ("1, 3, 5", 5, [0, 2, 4]),
        ("all", 4, [0, 1, 2, 3]),
        ("", 3, [0, 1, 2]),
        ("1; 2", 3, [0, 1]),
        ("99", 3, [0, 1, 2]),  # out of range → falls back to all
        ("1, 99, 2", 3, [0, 1]),  # mix: keep valid, drop invalid
        ("2, 2, 2", 3, [1]),  # dedup
        ("nope", 3, [0, 1, 2]),  # non-numeric → fall back to all
    ],
)
def test_parse_angle_selection(answer: str, available: int, expected: list[int]) -> None:
    assert parse_angle_selection(answer, available=available) == expected


@pytest.mark.parametrize(
    "answer, expected",
    [
        ("Hofstadter, Boden, divergent thinking", ["Hofstadter", "Boden", "divergent thinking"]),
        ("", []),
        ("   ", []),
        ("one; two; three", ["one", "two", "three"]),
        ("dup, dup, Other", ["dup", "Other"]),  # case-insensitive dedup, preserves first form
    ],
)
def test_parse_keywords(answer: str, expected: list[str]) -> None:
    assert parse_keywords(answer) == expected


@pytest.mark.parametrize(
    "answer, expected",
    [
        ("foundations", "foundations"),
        ("recent", "recent"),
        ("both", "both"),
        ("found", "foundations"),  # prefix
        ("rec", "recent"),
        ("", "both"),
        ("nonsense", "both"),
    ],
)
def test_parse_orientation(answer: str, expected: str) -> None:
    assert parse_orientation(answer) == expected


@pytest.mark.parametrize(
    "answer, expected",
    [
        ("30", 30),
        ("", DEFAULT_MAX_WORKS),
        ("0", 1),  # min clamp
        ("not a number", DEFAULT_MAX_WORKS),
        ("-3", 1),
    ],
)
def test_parse_max_works(answer: str, expected: int) -> None:
    assert parse_max_works(answer) == expected


# ---------- run_ceremony ----------


def _tree() -> AngleTree:
    return AngleTree(
        topic="creativity",
        angles=[
            Angle(name="cognitive", description="divergent thinking foundations"),
            Angle(name="computational", description="AI creativity"),
            Angle(name="art", description="generative-art systems"),
            Angle(name="organisational", description="creativity in firms"),
            Angle(name="analogy", description="Hofstadter / cross-domain"),
        ],
    )


def test_run_ceremony_happy_path_with_queued_prompter() -> None:
    prompter = QueuedPrompter(
        answers=[
            "1, 2, 5",  # angle selection
            "Hofstadter, Boden, divergent thinking",  # extra keywords
            "foundations",  # orientation
            "30",  # max works
        ]
    )
    plan = run_ceremony(_tree(), prompter=prompter)

    assert plan.topic == "creativity"
    assert plan.slug == "creativity"
    assert [a.name for a in plan.angles] == ["cognitive", "computational", "analogy"]
    assert plan.extra_keywords == ["Hofstadter", "Boden", "divergent thinking"]
    assert plan.orientation == "foundations"
    assert plan.max_works == 30
    assert plan.discovery is not None
    assert plan.discovery.topic == "creativity"


def test_run_ceremony_displays_angle_tree_before_asking() -> None:
    prompter = QueuedPrompter(answers=["all", "", "both", ""])
    run_ceremony(_tree(), prompter=prompter)
    assert prompter.display_log, "ceremony should have displayed the tree"
    rendered = prompter.display_log[0]
    assert "creativity" in rendered
    assert "cognitive" in rendered


def test_run_ceremony_auto_mode_skips_prompts() -> None:
    """auto=True must not call the prompter at all."""

    class BoomPrompter:
        def ask(self, question: str, default: str | None = None) -> str:
            raise AssertionError("auto mode should not prompt")

        def display(self, text: str) -> None:
            raise AssertionError("auto mode should not display")

    plan = run_ceremony(_tree(), prompter=BoomPrompter(), auto=True)
    assert plan.orientation == "both"
    assert plan.max_works == DEFAULT_MAX_WORKS
    assert len(plan.angles) == 5  # all angles


def test_auto_plan_keeps_all_angles() -> None:
    tree = _tree()
    plan = auto_plan(tree)
    assert len(plan.angles) == 5
    assert plan.orientation == "both"
    assert plan.discovery is tree


def test_run_ceremony_defaults_fill_in_on_empty_answers() -> None:
    """Pressing enter at every prompt should give the auto-equivalent plan."""
    prompter = QueuedPrompter(answers=["", "", "", ""])
    plan = run_ceremony(_tree(), prompter=prompter, max_works_default=42)
    assert len(plan.angles) == 5  # 'all' default
    assert plan.extra_keywords == []
    assert plan.orientation == "both"
    assert plan.max_works == 42
