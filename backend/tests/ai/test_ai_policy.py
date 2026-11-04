# ruff: noqa: E501, PLR0911
"""S6-T2 AC1, AC3 (policy part): AST policy for ``app/ai/`` (ADR 0016 points 2 and 3).

Scope is in README.md. The checkers take a source root, so planted bad modules prove that
they fail where they must. This file does not import ``app.ai`` (the checkers read source).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[2] / "app"
AI = APP / "ai"
GATE_TYPES = {"PseudonymizedDocument", "PseudonymizedClause", "PseudonymizedText", "ConfirmedTopic"}
ALLOWED_PARAM_LEAVES = GATE_TYPES | {
    "AIRequest",
    "PromptTemplate",
    "AIErrorCode",
    "int",
    "bool",
    "float",
    "None",
    "Optional",
    "Union",
    "Literal",
    "Final",
    "Annotated",
    "tuple",
    "Sequence",
}
EXEMPT_MODULES = {"factory.py", "presets.py"}
FIELD_FORBIDDEN = {"str", "bytes", "bytearray", "Any", "dict", "list", "set", "object", "Mapping"}
FIELD_ALLOWED = GATE_TYPES | {"PromptTemplate", "type", "BaseModel", "int", "None"}
SDK_ROOTS = {"anthropic", "openai"}
SDK_CLIENTS = {"Anthropic", "AsyncAnthropic", "OpenAI", "AsyncOpenAI"}


def _leaves(node: ast.AST) -> set[str]:
    if isinstance(node, ast.Constant):
        return {"None"} if node.value is None else {repr(node.value)}
    if isinstance(node, ast.Name):
        return {node.id}
    if isinstance(node, ast.Attribute):
        return {node.attr}
    if isinstance(node, ast.BinOp):
        return _leaves(node.left) | _leaves(node.right)
    if isinstance(node, ast.Subscript):
        base = _leaves(node.value)
        if base == {"Literal"}:
            return base
        return base | _leaves(node.slice)
    if isinstance(node, ast.Tuple):
        return set().union(*(_leaves(e) for e in node.elts)) if node.elts else set()
    return {ast.dump(node)}


def _ai_files(root: Path) -> list[Path]:
    return sorted((root / "ai").glob("**/*.py")) if (root / "ai").is_dir() else []


def _functions(tree: ast.Module) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    """Module-level functions and methods of module-level classes."""
    found: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            found.append(node)
        elif isinstance(node, ast.ClassDef):
            found += [
                n for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            ]
    return found


def public_surface_problems(root: Path) -> list[str]:
    problems: list[str] = []
    for path in _ai_files(root):
        rel = path.relative_to(root).as_posix()
        if path.name in EXEMPT_MODULES and path.parent.name == "ai":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        in_adapters = "adapters" in path.parts
        for func in _functions(tree):
            if func.name.startswith("_") and func.name != "__init__":
                continue
            if func.name == "__init__" and in_adapters:
                continue
            args = [*func.args.posonlyargs, *func.args.args, *func.args.kwonlyargs]
            if func.args.vararg:
                args.append(func.args.vararg)
            if func.args.kwarg:
                args.append(func.args.kwarg)
            for arg in args:
                if arg.arg in {"self", "cls"}:
                    continue
                if arg.annotation is None:
                    problems.append(f"{rel}:{func.lineno}: {func.name}({arg.arg}) unannotated")
                    continue
                bad = _leaves(arg.annotation) - ALLOWED_PARAM_LEAVES
                if bad:
                    problems.append(f"{rel}:{func.lineno}: {func.name}({arg.arg}: {sorted(bad)})")
    return problems


def request_field_problems(source: str) -> list[str]:
    """``AIRequest``: gate/template/schema fields only, no ``str``, exactly one document."""
    tree = ast.parse(source)
    cls = next(
        (n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "AIRequest"), None
    )
    if cls is None:
        return ["AIRequest is not defined"]
    problems: list[str] = []
    documents = 0
    for node in cls.body:
        if not isinstance(node, ast.AnnAssign):
            continue
        name = ast.unparse(node.target)
        leaves = _leaves(node.annotation)
        if leaves & FIELD_FORBIDDEN:
            problems.append(f"{name}: forbidden type {sorted(leaves & FIELD_FORBIDDEN)}")
        if leaves - FIELD_ALLOWED - FIELD_FORBIDDEN:
            problems.append(f"{name}: unknown type {sorted(leaves - FIELD_ALLOWED)}")
        if "PseudonymizedDocument" in leaves:
            documents += 1
            if ast.unparse(node.annotation) != "PseudonymizedDocument":
                problems.append(f"{name}: the document field must be a plain PseudonymizedDocument")
    if documents != 1:
        problems.append(f"{documents} document fields; exactly one is required")
    return problems


def sdk_import_problems(root: Path) -> list[str]:
    """Only ``app/ai/adapters/`` imports ``anthropic`` or ``openai``."""
    problems: list[str] = []
    for path in sorted(root.glob("**/*.py")):
        rel = path.relative_to(root)
        if rel.parts[:2] == ("ai", "adapters"):
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            problems += [f"{rel}: imports {n}" for n in names if n.split(".")[0] in SDK_ROOTS]
    return problems


def global_client_problems(root: Path) -> list[str]:
    """No SDK client is built at module level or in a class body (no global client holds a key)."""
    problems: list[str] = []
    for path in _ai_files(root):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        scopes: list[ast.AST] = [tree, *[n for n in tree.body if isinstance(n, ast.ClassDef)]]
        for scope in scopes:
            for stmt in scope.body:  # type: ignore[attr-defined]
                if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    continue
                for node in ast.walk(stmt):
                    if isinstance(node, ast.Call):
                        fn = node.func
                        called = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", "")
                        if called in SDK_CLIENTS:
                            problems.append(f"{path.name}:{node.lineno}: global {called}(...)")
    return problems


# --- the real repository ----------------------------------------------------------------------


def test_policy_ai_package_has_the_named_modules() -> None:
    for name in ("port.py", "prompting.py", "factory.py", "presets.py"):
        assert (AI / name).is_file(), name
    assert (AI / "prompts" / "__init__.py").is_file()
    assert (AI / "adapters").is_dir()
    assert {p.name for p in (AI / "adapters").glob("*.py")} >= {
        "anthropic.py",
        "openai_compatible.py",
    }


def test_policy_ai_public_surface_takes_no_str_or_bytes() -> None:
    assert _ai_files(APP), "app/ai/ is missing"
    assert public_surface_problems(APP) == []


def test_policy_ai_request_fields_are_gate_types_only_with_one_document() -> None:
    assert request_field_problems((AI / "port.py").read_text(encoding="utf-8")) == []


def test_policy_only_adapters_import_the_sdks() -> None:
    assert _ai_files(APP), "app/ai/ is missing"
    assert sdk_import_problems(APP) == []


def test_policy_adapters_import_both_sdks() -> None:
    text = "\n".join(p.read_text(encoding="utf-8") for p in (AI / "adapters").glob("*.py"))

    assert "anthropic" in text
    assert "openai" in text


def test_policy_no_global_sdk_client() -> None:
    assert _ai_files(APP), "app/ai/ is missing"
    assert global_client_problems(APP) == []


def test_policy_port_declares_no_litellm_or_tools() -> None:
    text = "\n".join(p.read_text(encoding="utf-8") for p in _ai_files(APP))

    assert "litellm" not in text.lower()


# --- the checkers catch planted bad code ------------------------------------------------------

_HEAD = "from app.pseudo.gate import PseudonymizedDocument\n"


def _plant(tmp_path: Path, where: str, source: str) -> Path:
    target = tmp_path / "app" / where
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(source, encoding="utf-8")
    return tmp_path / "app"


@pytest.mark.parametrize(
    ("where", "source"),
    [
        ("ai/port.py", "class P:\n    async def complete_json(self, text: str): ...\n"),
        ("ai/port.py", "class P:\n    async def check(self, probe: bytes): ...\n"),
        ("ai/port.py", "class P:\n    async def complete_json(self, request): ...\n"),
        ("ai/port.py", "class P:\n    async def complete_json(self, request: dict): ...\n"),
        ("ai/port.py", "class P:\n    async def f(self, *args: str): ...\n"),
        ("ai/port.py", "class P:\n    async def f(self, **kw: str): ...\n"),
        ("ai/prompting.py", "def build(text: str) -> str: ...\n"),
        ("ai/prompting.py", "def build(doc: str | PseudonymizedDocument): ...\n"),
        ("ai/prompts/x.py", "def render(t: str): ...\n"),
        (
            "ai/adapters/anthropic.py",
            "class A:\n    async def complete_json(self, text: str): ...\n",
        ),
    ],
)
def test_policy_surface_checker_flags_planted_module(
    tmp_path: Path, where: str, source: str
) -> None:
    root = _plant(tmp_path, where, _HEAD + source)

    assert public_surface_problems(root) != []


def test_policy_surface_checker_accepts_clean_module_private_helpers_and_exempt_modules(
    tmp_path: Path,
) -> None:
    _plant(
        tmp_path,
        "ai/port.py",
        _HEAD + "class P:\n    async def complete_json(self, request: AIRequest): ...\n"
        "def _helper(text: str, n: bytes): ...\n",
    )
    _plant(tmp_path, "ai/factory.py", "def provider_for(model: str, key: str): ...\n")
    _plant(tmp_path, "ai/presets.py", "def validate(model: str): ...\n")
    root = _plant(
        tmp_path,
        "ai/adapters/openai_compatible.py",
        "class A:\n    def __init__(self, key: str): ...\n",
    )

    assert public_surface_problems(root) == []


@pytest.mark.parametrize(
    "source",
    [
        "class AIRequest:\n    document: PseudonymizedDocument\n    prompt: str\n",
        "class AIRequest:\n    document: PseudonymizedDocument\n    extra: bytes\n",
        "class AIRequest:\n    document: PseudonymizedDocument\n    meta: dict[str, object]\n",
        "class AIRequest:\n    documents: tuple[PseudonymizedDocument, ...]\n",
        "class AIRequest:\n    documents: list[PseudonymizedDocument]\n",
        "class AIRequest:\n    a: PseudonymizedDocument\n    b: PseudonymizedDocument\n",
        "class AIRequest:\n    document: PseudonymizedDocument | None\n",
        "class AIRequest:\n    template: PromptTemplate\n",
        "class AIRequest:\n    document: PseudonymizedDocument\n    other: Foo\n",
    ],
)
def test_policy_request_checker_flags_planted_class(source: str) -> None:
    assert request_field_problems(_HEAD + source) != []


def test_policy_request_checker_accepts_a_good_class() -> None:
    source = (
        _HEAD
        + "class AIRequest:\n    template: PromptTemplate\n    document: PseudonymizedDocument\n"
        "    schema: type[BaseModel]\n    max_tokens: int\n    text: PseudonymizedText | None = None\n"
        "    topic: ConfirmedTopic | None = None\n"
    )

    assert request_field_problems(source) == []


@pytest.mark.parametrize(
    "statement", ["import anthropic", "from openai import AsyncOpenAI", "import openai.types"]
)
@pytest.mark.parametrize("where", ["ai/port.py", "ai/factory.py", "api/route.py", "net/client.py"])
def test_policy_sdk_import_checker_flags_planted_import(
    tmp_path: Path, where: str, statement: str
) -> None:
    root = _plant(tmp_path, where, statement + "\n")

    assert sdk_import_problems(root) != []


def test_policy_sdk_import_checker_accepts_adapters(tmp_path: Path) -> None:
    root = _plant(tmp_path, "ai/adapters/anthropic.py", "import anthropic\n")

    assert sdk_import_problems(root) == []


@pytest.mark.parametrize(
    "source",
    [
        "import anthropic\nCLIENT = anthropic.AsyncAnthropic(api_key='x')\n",
        "from openai import AsyncOpenAI\nCLIENT = AsyncOpenAI()\n",
        "class A:\n    client = AsyncOpenAI()\n",
    ],
)
def test_policy_global_client_checker_flags_planted_module(tmp_path: Path, source: str) -> None:
    root = _plant(tmp_path, "ai/adapters/x.py", source)

    assert global_client_problems(root) != []


def test_policy_global_client_checker_accepts_client_inside_a_method(tmp_path: Path) -> None:
    root = _plant(
        tmp_path,
        "ai/adapters/x.py",
        "class A:\n    async def check(self):\n        c = AsyncOpenAI()\n",
    )

    assert global_client_problems(root) == []
