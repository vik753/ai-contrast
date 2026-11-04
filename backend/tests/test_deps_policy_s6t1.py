"""S6-T1 items 2-4: dependency and import policy for the outbound client (ADR 0016 point 1)."""

from __future__ import annotations

import ast
import json
import re
import tomllib
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
APP = BACKEND / "app"
PYPROJECT = tomllib.loads((BACKEND / "pyproject.toml").read_text(encoding="utf-8"))
NEW = ("httpx2", "httpcore2")
OLD = ("httpx", "httpcore")


def imported_roots(source: str) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            roots |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".")[0])
    return roots


def _files(inside_net: bool) -> list[Path]:
    return [p for p in APP.rglob("*.py") if (p.relative_to(APP).parts[0] == "net") == inside_net]


def _pins(group: list[str]) -> dict[str, str]:
    pins: dict[str, str] = {}
    for spec in group:
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)\s*(==|>=|<=|~=|>|<)\s*(\S+)", spec.strip())
        if match:
            pins[match[1].lower()] = match[2] + match[3]
    return pins


def test_scanner_detects_new_and_old_imports() -> None:
    assert imported_roots("import httpx2.x\nfrom httpcore2 import a\n") == {"httpx2", "httpcore2"}
    assert imported_roots("import httpx\nfrom httpcore import a\n") == {"httpx", "httpcore"}


def test_app_net_is_scanned_and_imports_httpx2() -> None:
    roots = set().union(*(imported_roots(p.read_text("utf-8")) for p in _files(True)))

    assert _files(True)
    assert "httpx2" in roots
    assert "httpcore2" in roots


@pytest.mark.parametrize("path", _files(False), ids=lambda p: p.relative_to(APP).as_posix())
def test_module_outside_app_net_does_not_import_httpx2_or_httpcore2(path: Path) -> None:
    assert not imported_roots(path.read_text("utf-8")) & set(NEW)


@pytest.mark.parametrize(
    "path", _files(True) + _files(False), ids=lambda p: p.relative_to(APP).as_posix()
)
def test_no_module_under_app_imports_httpx_or_httpcore(path: Path) -> None:
    assert not imported_roots(path.read_text("utf-8")) & set(OLD)


def test_uv_lock_has_no_opentelemetry_sdk_or_exporter() -> None:
    lock = tomllib.loads((BACKEND / "uv.lock").read_text(encoding="utf-8"))
    names = {p["name"] for p in lock["package"]}

    assert "opentelemetry-sdk" not in names
    assert not {n for n in names if n.startswith("opentelemetry-exporter")}


def test_pyproject_pins_exact_runtime_versions() -> None:
    pins = _pins(PYPROJECT["project"]["dependencies"])

    assert pins.get("anthropic") in {"==1.15.0", "==1.14.0"}
    assert pins.get("openai") == "==3.31.0"
    assert pins.get("httpx2") == "==2.13.1"
    assert pins.get("httpcore2") == "==2.13.1"
    assert re.fullmatch(r"==\d[\w.]*", pins.get("certifi", "")), pins.get("certifi")


def test_httpx_is_a_dev_dependency_only() -> None:
    runtime = _pins(PYPROJECT["project"]["dependencies"])
    dev = _pins(PYPROJECT["dependency-groups"]["dev"])

    assert "httpx" not in runtime
    assert "httpx" in dev


def test_truststore_is_not_a_declared_dependency() -> None:
    declared = PYPROJECT["project"]["dependencies"] + PYPROJECT["dependency-groups"]["dev"]

    assert not [d for d in declared if d.lower().startswith("truststore")]


def test_uv_no_build_is_true() -> None:
    assert PYPROJECT["tool"]["uv"]["no-build"] is True


def test_log_config_sets_httpx2_and_httpcore2_to_warning() -> None:
    loggers = json.loads((BACKEND / "log_config.json").read_text("utf-8"))["loggers"]

    assert loggers["httpx2"]["level"] == "WARNING"
    assert loggers["httpcore2"]["level"] == "WARNING"
