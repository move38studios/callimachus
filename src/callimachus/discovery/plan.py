"""Plan and AngleTree models — the artifacts of the discovery ceremony.

A `Plan` is what M2.4's orchestrator consumes to fan out hunters. It's
produced by the M2.3 ceremony from a scout result + user answers, and
persisted as YAML so the user can review/edit before kicking off the
deep build (terraform plan/apply pattern).

Plans live at `<library_root>/.callimachus/plans/<slug>.yaml`.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

from callimachus.sources.protocols import WorkKind


class Angle(BaseModel):
    """One distinct sub-topic the library should cover."""

    name: str = Field(min_length=1, description="Short label (e.g. 'foundations').")
    description: str = Field(
        min_length=1, description="One-sentence explanation of what this angle covers."
    )
    keywords: list[str] = Field(
        default_factory=list,
        description="Search keywords the hunter will probe with.",
    )
    sample_titles: list[str] = Field(
        default_factory=list,
        description=(
            "Titles surfaced by a shallow probe. Lets the user calibrate whether "
            "this angle matches their intent."
        ),
    )
    hit_count: int = Field(
        default=0,
        description="Total candidates the probe source returned for this angle.",
    )


class AngleTree(BaseModel):
    """The scout's structured findings for a topic."""

    topic: str
    angles: list[Angle]
    related_fields: list[str] = Field(
        default_factory=list,
        description="Adjacent topics the user might consider if the scope feels off.",
    )
    notes: str = Field(default="", description="Free-text observations from the scout.")
    scout_model: str | None = None
    probe_source: str | None = None


class Plan(BaseModel):
    """A frozen build plan. The orchestrator runs this verbatim."""

    topic: str
    slug: str
    angles: list[Angle] = Field(
        description="The subset of scout angles the user committed to.",
    )
    extra_keywords: list[str] = Field(
        default_factory=list,
        description=(
            "Anchor terms the user supplied (authors, paper titles, "
            "specific concepts) beyond what's in each angle's keywords."
        ),
    )
    orientation: Literal["foundations", "recent", "both"] = "both"
    year_from: int | None = None
    year_to: int | None = None
    max_works: int = Field(default=50, ge=1)
    kinds: list[WorkKind] = Field(default_factory=lambda: ["paper"])
    source_names: list[str] | None = Field(
        default=None,
        description="If set, restrict hunters to these sources by name; default = all enabled.",
    )
    discovery: AngleTree | None = Field(
        default=None,
        description="Snapshot of the scout's AngleTree, for traceability.",
    )


# ---------- slug + path helpers ----------

_SLUG_FALLBACK = "topic"
_SLUG_RE = re.compile(r"[^a-z0-9-]+")
_MULTI_HYPHEN_RE = re.compile(r"-+")


def slugify(topic: str) -> str:
    """Make a topic filename-safe.

    >>> slugify("Diffusion Models for Image Generation")
    'diffusion-models-for-image-generation'
    >>> slugify("  ")
    'topic'
    """
    # Normalize unicode (e.g. é → e), lowercase, replace non-alphanumerics with hyphens
    normalized = unicodedata.normalize("NFKD", topic).encode("ascii", "ignore").decode("ascii")
    s = _SLUG_RE.sub("-", normalized.lower())
    s = _MULTI_HYPHEN_RE.sub("-", s).strip("-")
    return s or _SLUG_FALLBACK


def plans_dir(library_root: Path) -> Path:
    """Where plans live within a library."""
    return library_root / ".callimachus" / "plans"


def plan_path(library_root: Path, slug: str) -> Path:
    return plans_dir(library_root) / f"{slug}.yaml"


def save_plan(plan: Plan, library_root: Path) -> Path:
    """Write the plan to YAML on disk. Creates the plans/ directory if needed."""
    plans_dir(library_root).mkdir(parents=True, exist_ok=True)
    path = plan_path(library_root, plan.slug)
    data = plan.model_dump(mode="json", exclude_none=False)
    path.write_text(
        yaml.safe_dump(
            data, sort_keys=False, allow_unicode=True, default_flow_style=False, width=100
        )
    )
    return path


def load_plan(library_root: Path, slug: str) -> Plan:
    """Read a previously-saved plan back as a Pydantic model."""
    path = plan_path(library_root, slug)
    if not path.is_file():
        msg = f"plan not found at {path}"
        raise FileNotFoundError(msg)
    data = yaml.safe_load(path.read_text())
    return Plan.model_validate(data)
