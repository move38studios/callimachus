"""Smoke test — proves the package imports and pytest runs."""

from __future__ import annotations

import callimachus


def test_version_is_set() -> None:
    assert callimachus.__version__
    assert isinstance(callimachus.__version__, str)
    assert callimachus.__version__.startswith("0.")
