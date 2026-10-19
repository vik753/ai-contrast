"""`app.__version__` matches the version in pyproject.toml (backend-dev unit test)."""

from __future__ import annotations

import tomllib
from pathlib import Path

import app as app_package

PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


def test_version_matches_pyproject() -> None:
    project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]

    assert app_package.__version__ == project["version"]
