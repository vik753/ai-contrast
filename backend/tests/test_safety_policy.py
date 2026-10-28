# ruff: noqa: E501, PLR0912
"""S5b-T2 AC3: AST policy for the type gate (ADR 0008 point 3, ADR 0015 point 5).

Outside ``app/pseudo/gate.py``, in a module that uses a gate type: no constructor
call, ``cast``, ``__new__``, ``object.__setattr__``, ``dataclasses.replace``,
``copy.copy``/``copy.deepcopy``, ``pickle``, or sentinel use. No gate type in a
Pydantic request model or a route parameter. Modules under ``app/ai/`` (by glob;
none exist yet) may accept only gate types, enums and simple constants.

The checkers take a source root, so planted bad modules in a temp dir prove
that they fail where they must. Interface assumption for ``app/ai/``: allowed
annotation leaves are gate types, enum classes (defined in the module or named
``*Enum``/``*Kind``/``*Code``), ``bool``, ``int``, ``float``, ``None``, ``Literal``,
``Final``; ``str``, ``bytes``, ``Any``, ``dict``, ``list`` are refused.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parents[1] / "app"
GATE_TYPES = {"PseudonymizedDocument", "PseudonymizedClause", "PseudonymizedText", "ConfirmedTopic"}
FORBIDDEN_ATTR_CALLS = {
    ("object", "__setattr__"),
    ("dataclasses", "replace"),
    ("copy", "copy"),
    ("copy", "deepcopy"),
    ("copy", "replace"),
    ("pickle", "dumps"),
    ("pickle", "loads"),
    ("pickle", "dump"),
    ("pickle", "load"),
}
FORBIDDEN_NAME_CALLS = {"replace", "copy", "deepcopy", "cast", "dumps", "loads"}
FORBIDDEN_IMPORTS = {"pickle", "cPickle", "dill", "cloudpickle", "marshal", "shelve"}
WRAPPERS = {"tuple", "Sequence", "Optional", "Union", "Literal", "Final", "None", "Annotated"}
SIMPLE = {"bool", "int", "float"}
ENUM_BASES = {"Enum", "StrEnum", "IntEnum", "Flag", "IntFlag"}


def _py_files(root: Path) -> Iterator[Path]:
    yield from sorted(root.rglob("*.py"))


def _names(node: ast.AST) -> set[str]:
    out: set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name):
            out.add(sub.id)
        elif isinstance(sub, ast.Attribute):
            out.add(sub.attr)
        elif isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            out.update(_string_annotation_names(sub.value))
    return out


def _annotation_leaves(node: ast.AST) -> set[str]:
    """Names in an annotation; the arguments of ``Literal[...]`` are constants, not types."""
    if isinstance(node, ast.Subscript):
        base = node.value
        base_name = base.id if isinstance(base, ast.Name) else getattr(base, "attr", "")
        if base_name == "Literal":
            return {"Literal"}
        return _annotation_leaves(node.value) | _annotation_leaves(node.slice)
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        try:
            return _annotation_leaves(ast.parse(node.value, mode="eval").body)
        except SyntaxError:
            return set()
    if isinstance(node, (ast.Tuple, ast.List)):
        return set().union(*(_annotation_leaves(e) for e in node.elts)) if node.elts else set()
    if isinstance(node, ast.BinOp):
        return _annotation_leaves(node.left) | _annotation_leaves(node.right)
    if isinstance(node, ast.Name):
        return {node.id}
    if isinstance(node, ast.Attribute):
        return {node.attr}
    return set()


def _string_annotation_names(text: str) -> set[str]:
    try:
        return _names(ast.parse(text, mode="eval"))
    except SyntaxError:
        return set()


def _uses_gate(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module == "app.pseudo.gate" or (node.module or "").endswith("pseudo.gate"):
                return True
            if any(a.name in GATE_TYPES for a in node.names):
                return True
        elif (isinstance(node, ast.Name) and node.id in GATE_TYPES) or (
            isinstance(node, ast.Attribute) and node.attr in GATE_TYPES
        ):
            return True
    return False


def gate_use_problems(root: Path) -> list[str]:
    """Forbidden constructs in modules that use a gate type, outside gate.py."""
    problems: list[str] = []
    for path in _py_files(root):
        if path.name == "gate.py" and path.parent.name == "pseudo":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if not _uses_gate(tree):
            continue
        where = path.relative_to(root).as_posix()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                problems += [
                    f"{where}: import {a.name}" for a in node.names if a.name in FORBIDDEN_IMPORTS
                ]
            if isinstance(node, ast.ImportFrom):
                if (node.module or "") in FORBIDDEN_IMPORTS:
                    problems.append(f"{where}: from {node.module} import")
                problems += [
                    f"{where}: imports {a.name}"
                    for a in node.names
                    if "sentinel" in a.name.lower()
                    or (a.name.startswith("_") and "gate" in (node.module or ""))
                ]
            if isinstance(node, ast.Attribute) and node.attr in {"__new__", "__setattr__"}:
                problems.append(f"{where}:{node.lineno}: .{node.attr}")
            if isinstance(node, (ast.Name, ast.Attribute)):
                name = node.id if isinstance(node, ast.Name) else node.attr
                if "sentinel" in name.lower():
                    problems.append(f"{where}:{node.lineno}: sentinel")
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name):
                    if func.id in GATE_TYPES:
                        problems.append(f"{where}:{node.lineno}: constructor {func.id}")
                    elif func.id in FORBIDDEN_NAME_CALLS:
                        problems.append(f"{where}:{node.lineno}: call {func.id}")
                elif isinstance(func, ast.Attribute):
                    if func.attr in GATE_TYPES:
                        problems.append(f"{where}:{node.lineno}: constructor {func.attr}")
                    base = func.value.id if isinstance(func.value, ast.Name) else ""
                    if (base, func.attr) in FORBIDDEN_ATTR_CALLS or func.attr == "cast":
                        problems.append(f"{where}:{node.lineno}: call {base}.{func.attr}")
    return problems


def _is_pydantic_model(cls: ast.ClassDef) -> bool:
    return any(
        (isinstance(b, ast.Name) and b.id in {"BaseModel", "RootModel"})
        or (isinstance(b, ast.Attribute) and b.attr in {"BaseModel", "RootModel"})
        or (isinstance(b, ast.Name) and b.id.endswith("Model"))
        for b in cls.bases
    )


def request_model_problems(root: Path) -> list[str]:
    problems: list[str] = []
    for path in _py_files(root):
        if path.name == "gate.py" and path.parent.name == "pseudo":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        where = path.relative_to(root).as_posix()
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and _is_pydantic_model(node):
                for item in node.body:
                    if isinstance(item, ast.AnnAssign) and _names(item.annotation) & GATE_TYPES:
                        problems.append(f"{where}:{item.lineno}: gate type in model {node.name}")
            if (
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and path.parent.name == "api"
            ):
                args = [*node.args.args, *node.args.kwonlyargs, *node.args.posonlyargs]
                for arg in args:
                    if arg.annotation is not None and _names(arg.annotation) & GATE_TYPES:
                        problems.append(f"{where}:{node.lineno}: gate type in route {node.name}")
    return problems


def ai_module_problems(root: Path) -> list[str]:
    """Every function/method parameter in ``app/ai/**`` must be a gate type, enum or constant."""
    problems: list[str] = []
    for path in sorted((root / "ai").glob("**/*.py")) if (root / "ai").is_dir() else []:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        enums = {
            c.name
            for c in ast.walk(tree)
            if isinstance(c, ast.ClassDef)
            and any(
                (b.id if isinstance(b, ast.Name) else getattr(b, "attr", "")) in ENUM_BASES
                for b in c.bases
            )
        }
        where = path.relative_to(root).as_posix()
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            args = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
            if node.args.vararg:
                args.append(node.args.vararg)
            if node.args.kwarg:
                args.append(node.args.kwarg)
            for arg in args:
                if arg.arg in {"self", "cls"}:
                    continue
                if arg.annotation is None:
                    problems.append(f"{where}:{node.lineno}: {node.name}({arg.arg}) unannotated")
                    continue
                for leaf in _annotation_leaves(arg.annotation):
                    if (
                        leaf not in GATE_TYPES
                        and leaf not in enums
                        and leaf not in WRAPPERS
                        and leaf not in SIMPLE
                        and not leaf.endswith(("Enum", "Kind", "Code"))
                        and not leaf.isupper()
                    ):
                        problems.append(f"{where}:{node.lineno}: {node.name}({arg.arg}: {leaf})")
    return problems


# --- the real repository ------------------------------------------------------------------


def test_policy_gate_module_exists() -> None:
    assert (APP_DIR / "pseudo" / "gate.py").is_file()


def test_policy_gate_names_are_defined_only_in_gate_py() -> None:
    defining = [
        p.relative_to(APP_DIR).as_posix()
        for p in _py_files(APP_DIR)
        for n in ast.walk(ast.parse(p.read_text(encoding="utf-8")))
        if isinstance(n, ast.ClassDef) and n.name in GATE_TYPES
    ]

    assert sorted(defining) == ["pseudo/gate.py"] * 4


def test_policy_no_forbidden_gate_construct_outside_gate_py() -> None:
    assert gate_use_problems(APP_DIR) == []


def test_policy_no_gate_type_in_pydantic_models_or_route_parameters() -> None:
    assert request_model_problems(APP_DIR) == []


def test_policy_app_ai_modules_accept_only_gate_types_enums_and_constants() -> None:
    assert ai_module_problems(APP_DIR) == []


def test_policy_safety_pass_is_defined_in_gate_py_only() -> None:
    text = (APP_DIR / "pseudo" / "gate.py").read_text(encoding="utf-8")
    tree = ast.parse(text)
    funcs = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
    elsewhere = [
        p.name
        for p in _py_files(APP_DIR)
        if p.name != "gate.py"
        for n in ast.walk(ast.parse(p.read_text(encoding="utf-8")))
        if isinstance(n, ast.FunctionDef) and n.name == "safety_pass"
    ]

    assert "safety_pass" in funcs
    assert elsewhere == []


# --- the checkers catch planted bad modules ---------------------------------------------------------

_HEAD = "from app.pseudo.gate import PseudonymizedDocument, PseudonymizedText\n"
BAD_GATE_USES = {
    "constructor": "def f(x):\n    return PseudonymizedText(x)\n",
    "constructor-attr": "import app.pseudo.gate as g\ndef f(x):\n    return g.PseudonymizedDocument(x)\n",
    "cast": "from typing import cast\ndef f(x):\n    return cast(PseudonymizedText, x)\n",
    "cast-attr": "import typing\ndef f(x):\n    return typing.cast(PseudonymizedText, x)\n",
    "new": "def f():\n    return PseudonymizedText.__new__(PseudonymizedText)\n",
    "object-setattr": "def f(x):\n    object.__setattr__(x, 'text', 'y')\n",
    "replace": "import dataclasses\ndef f(x):\n    return dataclasses.replace(x)\n",
    "replace-from": "from dataclasses import replace\ndef f(x):\n    return replace(x)\n",
    "copy": "import copy\ndef f(x):\n    return copy.copy(x)\n",
    "deepcopy": "import copy\ndef f(x):\n    return copy.deepcopy(x)\n",
    "pickle": "import pickle\ndef f(x):\n    return pickle.loads(x)\n",
    "sentinel": "from app.pseudo.gate import _SENTINEL\n",
    "sentinel-attr": "import app.pseudo.gate as g\nX = g._SENTINEL\n",
}


@pytest.mark.parametrize("name", sorted(BAD_GATE_USES))
@pytest.mark.parametrize("where", ["other.py", "ai/provider.py", "api/route.py"])
def test_policy_gate_use_checker_flags_planted_module(
    tmp_path: Path, name: str, where: str
) -> None:
    target = tmp_path / "app" / where
    target.parent.mkdir(parents=True)
    target.write_text(_HEAD + BAD_GATE_USES[name], encoding="utf-8")

    assert gate_use_problems(tmp_path / "app") != []


def test_policy_gate_use_checker_accepts_clean_consumer(tmp_path: Path) -> None:
    target = tmp_path / "app" / "ai" / "provider.py"
    target.parent.mkdir(parents=True)
    target.write_text(
        _HEAD + "def use(doc: PseudonymizedDocument) -> int:\n    return len(doc.clauses)\n",
        encoding="utf-8",
    )

    assert gate_use_problems(tmp_path / "app") == []


def test_policy_gate_use_checker_ignores_gate_py_itself(tmp_path: Path) -> None:
    target = tmp_path / "app" / "pseudo" / "gate.py"
    target.parent.mkdir(parents=True)
    target.write_text(
        "import copy, pickle\nclass PseudonymizedText: ...\nx = PseudonymizedText()\n"
        "object.__setattr__(x, 'a', 1)\n",
        encoding="utf-8",
    )

    assert gate_use_problems(tmp_path / "app") == []


def test_policy_request_model_checker_flags_gate_type_in_pydantic_model(tmp_path: Path) -> None:
    target = tmp_path / "app" / "api" / "m.py"
    target.parent.mkdir(parents=True)
    target.write_text(
        "from pydantic import BaseModel\n"
        + _HEAD
        + "class Body(BaseModel):\n    doc: PseudonymizedDocument\n",
        encoding="utf-8",
    )

    assert request_model_problems(tmp_path / "app") != []


def test_policy_request_model_checker_flags_nested_and_optional_gate_type(tmp_path: Path) -> None:
    target = tmp_path / "app" / "x.py"
    target.parent.mkdir(parents=True)
    target.write_text(
        "from pydantic import BaseModel\n"
        + _HEAD
        + "class Body(BaseModel):\n    docs: list[PseudonymizedText] | None = None\n",
        encoding="utf-8",
    )

    assert request_model_problems(tmp_path / "app") != []


def test_policy_request_model_checker_flags_route_parameter(tmp_path: Path) -> None:
    target = tmp_path / "app" / "api" / "r.py"
    target.parent.mkdir(parents=True)
    target.write_text(
        _HEAD + "async def route(body: PseudonymizedDocument) -> None:\n    return None\n",
        encoding="utf-8",
    )

    assert request_model_problems(tmp_path / "app") != []


def test_policy_request_model_checker_accepts_plain_model(tmp_path: Path) -> None:
    target = tmp_path / "app" / "api" / "m.py"
    target.parent.mkdir(parents=True)
    target.write_text(
        "from pydantic import BaseModel\nclass Body(BaseModel):\n    text: str\n",
        encoding="utf-8",
    )

    assert request_model_problems(tmp_path / "app") == []


@pytest.mark.parametrize(
    "signature",
    [
        "def complete(self, prompt: str) -> None: ...",
        "def complete(self, prompt: bytes) -> None: ...",
        "def complete(self, data: dict[str, str]) -> None: ...",
        "def complete(self, doc: PseudonymizedDocument, extra: str) -> None: ...",
        "def complete(self, doc: PseudonymizedDocument, *, hint) -> None: ...",
        "def complete(self, doc: Any) -> None: ...",
        "def complete(self, *args: str) -> None: ...",
        "async def complete(self, **kw: str) -> None: ...",
    ],
)
def test_policy_ai_checker_flags_planted_str_parameter_in_temp_dir(
    tmp_path: Path, signature: str
) -> None:
    target = tmp_path / "app" / "ai" / "provider.py"
    target.parent.mkdir(parents=True)
    target.write_text(
        "from typing import Any\n" + _HEAD + f"class P:\n    {signature}\n", encoding="utf-8"
    )

    assert ai_module_problems(tmp_path / "app") != []


def test_policy_ai_checker_flags_nested_directory_module(tmp_path: Path) -> None:
    target = tmp_path / "app" / "ai" / "adapters" / "x.py"
    target.parent.mkdir(parents=True)
    target.write_text("def f(prompt: str) -> None: ...\n", encoding="utf-8")

    assert ai_module_problems(tmp_path / "app") != []


def test_policy_ai_checker_accepts_gate_types_enums_and_constants(tmp_path: Path) -> None:
    target = tmp_path / "app" / "ai" / "provider.py"
    target.parent.mkdir(parents=True)
    target.write_text(
        "import enum\nfrom typing import Literal\n"
        + _HEAD
        + "class Reason(enum.Enum):\n    A = 1\n"
        "class P:\n"
        "    def complete(self, doc: PseudonymizedDocument, why: Reason, limit: int,\n"
        "                 topics: tuple[PseudonymizedText, ...], mode: Literal['a']) -> None: ...\n",
        encoding="utf-8",
    )

    assert ai_module_problems(tmp_path / "app") == []


def test_policy_ai_checker_passes_vacuously_without_an_ai_directory(tmp_path: Path) -> None:
    (tmp_path / "app").mkdir()

    assert ai_module_problems(tmp_path / "app") == []
