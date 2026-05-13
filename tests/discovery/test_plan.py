"""Tests for the Plan model + YAML persistence."""

from __future__ import annotations

from pathlib import Path

import pytest

from callimachus.discovery.plan import (
    Angle,
    AngleTree,
    Plan,
    load_plan,
    plan_path,
    save_plan,
    slugify,
)


@pytest.mark.parametrize(
    "topic, expected",
    [
        ("Diffusion Models for Image Generation", "diffusion-models-for-image-generation"),
        ("creativity", "creativity"),
        ("  ", "topic"),
        ("Hofstadter & Gödel", "hofstadter-godel"),
        ("Émilie du Châtelet", "emilie-du-chatelet"),
        ("multi---hyphens---ok", "multi-hyphens-ok"),
        ("UPPER CASE Topic!", "upper-case-topic"),
    ],
)
def test_slugify(topic: str, expected: str) -> None:
    assert slugify(topic) == expected


def test_save_and_load_plan_roundtrip(tmp_path: Path) -> None:
    angle = Angle(
        name="foundations",
        description="seminal early work",
        keywords=["nonequilibrium", "diffusion"],
        sample_titles=["Sohl-Dickstein 2015"],
        hit_count=3,
    )
    tree = AngleTree(
        topic="diffusion models",
        angles=[angle],
        related_fields=["score matching"],
        notes="early scout note",
        scout_model="openrouter:anthropic/claude-haiku-4.5",
        probe_source="openalex",
    )
    plan = Plan(
        topic="diffusion models",
        slug="diffusion-models",
        angles=[angle],
        extra_keywords=["DDPM"],
        orientation="foundations",
        max_works=30,
        discovery=tree,
    )

    written_path = save_plan(plan, tmp_path)
    assert written_path == plan_path(tmp_path, "diffusion-models")
    assert written_path.exists()

    loaded = load_plan(tmp_path, "diffusion-models")
    assert loaded.topic == plan.topic
    assert loaded.slug == plan.slug
    assert loaded.orientation == "foundations"
    assert loaded.max_works == 30
    assert loaded.extra_keywords == ["DDPM"]
    assert loaded.angles[0].sample_titles == ["Sohl-Dickstein 2015"]
    assert loaded.discovery is not None
    assert loaded.discovery.probe_source == "openalex"


def test_save_plan_creates_plans_subdir(tmp_path: Path) -> None:
    tree = AngleTree(topic="x", angles=[Angle(name="a", description="ok ok ok")])
    plan = Plan(topic="x", slug="x", angles=tree.angles, discovery=tree)
    save_plan(plan, tmp_path)
    assert (tmp_path / ".callimachus" / "plans" / "x.yaml").exists()


def test_load_plan_missing_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_plan(tmp_path, "no-such-slug")


def test_plan_max_works_must_be_positive() -> None:
    from pydantic import ValidationError

    angle = Angle(name="a", description="ok ok ok")
    with pytest.raises(ValidationError):
        Plan(topic="x", slug="x", angles=[angle], max_works=0)
