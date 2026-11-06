# ruff: noqa: E501, PLR0912
"""S9-T2 AC2 / ADR 0019 point 10: at most one ``PseudonymizedDocument`` per AI function and request.

AST over ``app/ai/``, ``app/analysis/`` and ``app/tagging/``. The checker takes a source root, so
planted bad modules prove that it fails where it must. The wire part fails a captured request
that holds placeholders of two labels.
"""

from __future__ import annotations

import ast
import dataclasses
from pathlib import Path

import pytest

from app.ai.port import AIRequest, OutputLanguage, RateOtherRequest, RateTopicRequest
from app.analysis.rate import rate_other, rate_topic
from tests.canary.harness import WireCapture

from .helpers import FakeProvider, doc, other_answer, rating_topic, run, topic_answer

APP = Path(__file__).resolve().parents[2] / "app"
DOC = "PseudonymizedDocument"
SCOPE = ("ai", "analysis", "tagging")
REQUEST_BASES = {"AIRequest", "TaggingRequest", "RateTopicRequest", "RateOtherRequest"}


def _mentions(node: ast.AST | None) -> int:
    if node is None:
        return 0
    return sum(
        1
        for n in ast.walk(node)
        if (isinstance(n, ast.Name) and n.id == DOC)
        or (isinstance(n, ast.Attribute) and n.attr == DOC)
        or (isinstance(n, ast.Constant) and isinstance(n.value, str) and DOC in n.value)
    )


def _is_plain(node: ast.AST | None) -> bool:
    """``PseudonymizedDocument`` or ``PseudonymizedDocument | None`` (no container)."""
    if node is None:
        return True
    text = ast.unparse(node).replace(" ", "")
    return text.strip("'\"") in {DOC, f"{DOC}|None", f"None|{DOC}"}


def one_document_problems(root: Path) -> list[str]:
    problems: list[str] = []
    for scope in SCOPE:
        for path in sorted((root / scope).glob("**/*.py")):
            rel = path.relative_to(root).as_posix()
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    args = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
                    if node.args.vararg:
                        args.append(node.args.vararg)
                    if node.args.kwarg:
                        args.append(node.args.kwarg)
                    counted = 0
                    for arg in args:
                        if _mentions(arg.annotation) and not _is_plain(arg.annotation):
                            problems.append(
                                f"{rel}:{node.lineno}: {node.name}({arg.arg}) holds documents in a container"
                            )
                        counted += bool(_mentions(arg.annotation))
                    if counted > 1:
                        problems.append(
                            f"{rel}:{node.lineno}: {node.name} takes {counted} documents"
                        )
                    if _mentions(node.returns) and not _is_plain(node.returns):
                        problems.append(
                            f"{rel}:{node.lineno}: {node.name} returns documents in a container"
                        )
                elif isinstance(node, ast.ClassDef):
                    fields = [
                        n
                        for n in node.body
                        if isinstance(n, ast.AnnAssign) and _mentions(n.annotation)
                    ]
                    inherited = any(
                        (isinstance(b, ast.Name) and b.id in REQUEST_BASES) for b in node.bases
                    )
                    total = len(fields) + (1 if inherited else 0)
                    if node.name == "AIRequest":
                        total = len(fields)
                    if total > 1:
                        problems.append(
                            f"{rel}:{node.lineno}: class {node.name} holds {total} documents"
                        )
                    problems += [
                        f"{rel}:{f.lineno}: class {node.name} field holds documents in a container"
                        for f in fields
                        if not _is_plain(f.annotation)
                    ]
    return problems


def _plant(tmp_path: Path, source: str, scope: str = "analysis") -> Path:
    (tmp_path / scope).mkdir(parents=True, exist_ok=True)
    (tmp_path / scope / "bad.py").write_text(source, encoding="utf-8")
    return tmp_path


def test_policy_real_tree_has_at_most_one_document_per_function_and_request() -> None:
    assert one_document_problems(APP) == []


@pytest.mark.parametrize(
    ("scope", "source"),
    [
        ("analysis", "def f(a: PseudonymizedDocument, b: PseudonymizedDocument) -> None: ..."),
        (
            "tagging",
            "async def f(a: PseudonymizedDocument | None, *, b: PseudonymizedDocument) -> None: ...",
        ),
        ("ai", "def f(docs: Sequence[PseudonymizedDocument]) -> None: ..."),
        ("analysis", "def f(docs: tuple[PseudonymizedDocument, ...]) -> None: ..."),
        ("analysis", "def f(docs: dict[str, PseudonymizedDocument]) -> None: ..."),
        ("analysis", "def f(a: 'PseudonymizedDocument', b: 'PseudonymizedDocument') -> None: ..."),
        ("ai", "def f() -> list[PseudonymizedDocument]: ..."),
        ("analysis", "class R(AIRequest):\n    second: PseudonymizedDocument"),
        ("analysis", "class R(RateTopicRequest):\n    other: PseudonymizedDocument | None = None"),
        (
            "tagging",
            "class R:\n    a: PseudonymizedDocument\n    b: PseudonymizedDocument | None = None",
        ),
        ("ai", "class R:\n    docs: tuple[PseudonymizedDocument, ...] = ()"),
    ],
)
def test_policy_checker_flags_planted_bad_modules(tmp_path: Path, scope: str, source: str) -> None:
    assert one_document_problems(_plant(tmp_path, source, scope)) != []


@pytest.mark.parametrize(
    "source",
    [
        "def f(a: PseudonymizedDocument, t: PseudonymizedText, c: ConfirmedTopic) -> None: ...",
        "def f(a: PseudonymizedDocument | None = None) -> PseudonymizedDocument: ...",
        "class R(AIRequest):\n    language: str = 'en'",
        "class R:\n    document: PseudonymizedDocument | None = None",
    ],
)
def test_policy_checker_accepts_one_document(tmp_path: Path, source: str) -> None:
    assert one_document_problems(_plant(tmp_path, source)) == []


def test_policy_rate_requests_have_exactly_one_document_field() -> None:
    for kind in (RateTopicRequest, RateOtherRequest):
        names = [f.name for f in dataclasses.fields(kind) if DOC in str(f.type)]
        assert names == ["document"], kind
    assert issubclass(RateTopicRequest, AIRequest)


def test_wire_two_labels_in_one_captured_request_fail_the_canary() -> None:
    capture = WireCapture()
    capture.record("system ... [A.EMAIL_1] and [B.PERSON_2] ...")

    assert capture.label_mixes() == ["A+B"]


def test_wire_one_label_in_each_captured_request_passes_the_canary() -> None:
    capture = WireCapture()
    capture.record("[A.EMAIL_1] [A.PERSON_1]")
    capture.record("[B.EMAIL_1]")

    assert capture.label_mixes() == []


@pytest.mark.parametrize("kind", ["topic", "other"])
def test_wire_rating_request_holds_placeholders_of_one_label_only(kind: str) -> None:
    document = doc(
        "1. Notices go to [A.EMAIL_1].",
        "2. Contact [A.PERSON_1] about the claim.",
        "3. Plain clause.",
        label="A",
    )
    capture = WireCapture()
    if kind == "topic":
        provider = FakeProvider(topic_answer(findings=[], attributes=[]))
        run(rate_topic(provider, document, rating_topic(), language=OutputLanguage.EN))
    else:
        provider = FakeProvider(other_answer())
        run(rate_other(provider, document, side="insured", language=OutputLanguage.EN))
    for index in range(len(provider.requests)):
        capture.record("\n".join(m.content for m in provider.messages(index)))

    assert capture.captured
    assert any("[A.EMAIL_1]" in c for c in capture.captured)
    assert capture.label_mixes() == []
