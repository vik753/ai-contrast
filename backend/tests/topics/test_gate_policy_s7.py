"""S7-T1 AC4 and AC6: policy tests (AST) for ``confirm_topic`` and the check endpoint hooks."""

from __future__ import annotations

import ast
from pathlib import Path

APP = Path(__file__).resolve().parents[2] / "app"
GATE_TYPES = {"ConfirmedTopic", "ConfirmedAttribute"}


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _py_files() -> list[Path]:
    return sorted(p for p in APP.rglob("*.py") if "__pycache__" not in p.parts)


def test_policy_confirm_topic_is_defined_in_gate_py_only() -> None:
    defining = [
        p.relative_to(APP).as_posix()
        for p in _py_files()
        for n in ast.walk(_tree(p))
        if isinstance(n, ast.FunctionDef) and n.name == "confirm_topic"
    ]

    assert defining == ["pseudo/gate.py"]


def test_policy_confirmed_types_are_defined_in_gate_py_only() -> None:
    defining = sorted(
        (p.relative_to(APP).as_posix(), n.name)
        for p in _py_files()
        for n in ast.walk(_tree(p))
        if isinstance(n, ast.ClassDef) and n.name in GATE_TYPES
    )

    assert defining == [
        ("pseudo/gate.py", "ConfirmedAttribute"),
        ("pseudo/gate.py", "ConfirmedTopic"),
    ]


def test_policy_confirmed_types_are_built_only_inside_confirm_functions_of_gate_py() -> None:
    problems: list[str] = []
    for path in _py_files():
        tree = _tree(path)
        in_gate = path == APP / "pseudo" / "gate.py"
        for func in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
            allowed = in_gate and "confirm" in func.name
            for node in ast.walk(func):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id in GATE_TYPES
                    and not allowed
                ):
                    problems.append(f"{path.name}:{node.lineno} {node.func.id}( in {func.name}")
        if not in_gate:
            for node in tree.body:
                for call in ast.walk(node):
                    if (
                        isinstance(call, ast.Call)
                        and isinstance(call.func, ast.Name)
                        and call.func.id in GATE_TYPES
                        and not isinstance(node, ast.FunctionDef)
                    ):
                        problems.append(f"{path.name}:{call.lineno} module-level {call.func.id}(")

    assert problems == []


def test_policy_catalog_and_safety_modules_exist() -> None:
    assert (APP / "topics" / "catalog.py").is_file()
    assert (APP / "topics" / "safety.py").is_file()
    assert (APP / "topics" / "model.py").is_file()


def test_policy_provider_check_has_no_app_state_hook_fallback() -> None:
    source = (APP / "api" / "provider_check.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    hooks = {"provider_transport", "turnstile_transport", "clock"}
    problems: list[str] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and len(node.args) >= 2
        ):
            name = node.args[1]
            first = ast.unparse(node.args[0])
            if "state" in first and not (
                isinstance(name, ast.Constant) and name.value == "check_state"
            ):
                problems.append(f"line {node.lineno}: getattr on state")
            if isinstance(name, ast.Constant) and name.value in hooks:
                problems.append(f"line {node.lineno}: getattr {name.value}")
        if (
            isinstance(node, ast.Attribute)
            and node.attr in hooks
            and isinstance(node.value, ast.Attribute)
            and node.value.attr == "state"
        ):
            problems.append(f"line {node.lineno}: app.state.{node.attr}")

    assert problems == []


def test_policy_create_app_forwards_hooks_to_install() -> None:
    tree = _tree(APP / "main.py")
    create = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "create_app")
    names = {a.arg for a in create.args.kwonlyargs}

    assert {"provider_transport", "turnstile_transport", "clock"} <= names
