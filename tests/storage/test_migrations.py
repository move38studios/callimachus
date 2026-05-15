"""Migration round-trip test: upgrade head → verify → downgrade base → verify."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import Engine

from callimachus.storage import make_engine, make_session

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"


def _table_names(engine: Engine) -> set[str]:
    with make_session(engine) as session:
        result = session.connection().execute(
            text("SELECT name FROM sqlite_master WHERE type='table'")
        )
        rows = cast("list[tuple[str]]", result.all())
    return {r[0] for r in rows}


def test_migration_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "lib.db"
    db_url = f"sqlite:///{db_path}"
    monkeypatch.setenv("CALLIMACHUS_DATABASE_URL", db_url)

    cfg = Config(str(ALEMBIC_INI))

    # Upgrade to head and verify our tables exist
    command.upgrade(cfg, "head")
    engine = make_engine(db_url)
    after_upgrade = _table_names(engine)
    expected = {"works", "chunks", "collections", "work_collections", "runs"}
    assert expected.issubset(after_upgrade), (
        f"missing tables after upgrade: {expected - after_upgrade}"
    )
    # Alembic's bookkeeping table
    assert "alembic_version" in after_upgrade

    # Downgrade and verify our tables are gone
    command.downgrade(cfg, "base")
    after_downgrade = _table_names(engine)
    assert expected.isdisjoint(after_downgrade), (
        f"tables still present after downgrade: {expected & after_downgrade}"
    )
