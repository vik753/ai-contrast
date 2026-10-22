"""S2-T1 policy tests: AC6 (never on disk), AC9 (CI smoke through the
frontend proxy) and AC10 (no new dependency). ADR 0010, threats T3, T4, T8.

- ``app/`` must not use ``UploadFile``, ``request.form``, ``tempfile`` or
  ``SpooledTemporaryFile``. The check walks the AST, so a docstring or a
  comment that names them is fine; code that uses them is not.
- ``uv.lock`` must not contain ``python-multipart``.
- The CI ``compose`` job posts a small text body to ``/api/extract`` through
  the frontend proxy and expects ``"kind":"text"``.
"""

from __future__ import annotations

import ast
import re
import tomllib
from pathlib import Path

import pytest

from tests.test_repo_policy import _job_runs, _jobs, _run_blocks, _text, _workflow

BACKEND = Path(__file__).resolve().parents[1]
APP_DIR = BACKEND / "app"
UV_LOCK = BACKEND / "uv.lock"
PYPROJECT = BACKEND / "pyproject.toml"

FORBIDDEN_NAMES = {"UploadFile", "SpooledTemporaryFile"}
FORBIDDEN_MODULES = {"tempfile"}
FORBIDDEN_ATTRIBUTES = {"form", "UploadFile", "SpooledTemporaryFile"}

# defusedxml: approved for S3-T2 (DOCX walker); pdfminer.six: approved for S3-T3 (PDF);
# see docs/agent/TASKS.md "Stage 3 dependencies".
# S3-T6 (ADR 0012): httpx moved from dev to runtime (outbound HTTP through the guard).
RUNTIME_DEPENDENCIES = {
    "defusedxml",
    "fastapi",
    "httpx",
    "pdfminer-six",
    "pydantic-settings",
    "uvicorn",
}
DEV_DEPENDENCIES = {"mypy", "pip-audit", "pytest", "ruff"}


def _violations(source: str) -> list[str]:  # noqa: PLR0912 - one branch per rule
    """Forbidden uses in one Python source text."""
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in FORBIDDEN_MODULES:
                    found.append(f"import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            module = (node.module or "").split(".")[0]
            if module in FORBIDDEN_MODULES:
                found.append(f"from {node.module} import")
            for alias in node.names:
                if alias.name in FORBIDDEN_NAMES:
                    found.append(f"import of {alias.name}")
        elif isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES | FORBIDDEN_MODULES:
            found.append(f"name {node.id}")
        elif isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_ATTRIBUTES:
            found.append(f"attribute .{node.attr}")
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "__import__"
        ) or (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "import_module"
        ):
            for arg in node.args:
                if isinstance(arg, ast.Constant) and arg.value in FORBIDDEN_MODULES:
                    found.append(f"dynamic import of {arg.value}")
    return found


def _app_sources() -> list[Path]:
    return sorted(APP_DIR.rglob("*.py"))


# --- The scanner itself -----------------------------------------------------------


@pytest.mark.parametrize(
    "snippet",
    [
        "from fastapi import UploadFile",
        "from starlette.datastructures import UploadFile as U",
        "import fastapi\nx: fastapi.UploadFile",
        "async def f(request):\n    return await request.form()",
        "import tempfile",
        "import tempfile as t",
        "from tempfile import SpooledTemporaryFile",
        "from tempfile import NamedTemporaryFile",
        "x = SpooledTemporaryFile()",
        "import importlib\nimportlib.import_module('tempfile')",
        "__import__('tempfile')",
    ],
)
def test_policy_scanner_finds_forbidden_use(snippet: str) -> None:
    assert _violations(snippet) != []


@pytest.mark.parametrize(
    "snippet",
    [
        '"""We never use UploadFile, request.form(), tempfile or SpooledTemporaryFile."""',
        "# no tempfile here\nx = 1",
        "async def f(request):\n    return await request.body()",
        "formatted = 'a'.format()",
    ],
)
def test_policy_scanner_ignores_docs_and_safe_code(snippet: str) -> None:
    assert _violations(snippet) == []


# --- AC6: never on disk ------------------------------------------------------------


def test_policy_app_contains_extract_modules() -> None:
    names = {p.relative_to(APP_DIR).as_posix() for p in _app_sources()}

    assert {
        "api/extract.py",
        "extraction/detect.py",
        "extraction/limiter.py",
        "middleware/body_limit.py",
    } <= names


def test_policy_app_never_uses_upload_file_form_or_tempfile() -> None:
    found = {
        p.relative_to(BACKEND).as_posix(): v
        for p in _app_sources()
        if (v := _violations(p.read_text(encoding="utf-8")))
    }

    assert found == {}


def test_policy_uv_lock_has_no_python_multipart() -> None:
    text = UV_LOCK.read_text(encoding="utf-8").lower()

    assert not re.search(r"python[-_.]?multipart", text)


def test_policy_pyproject_has_no_python_multipart() -> None:
    text = PYPROJECT.read_text(encoding="utf-8").lower()

    assert not re.search(r"python[-_.]?multipart", text)


# --- AC10: no new dependency ---------------------------------------------------------


def _requirement_names(requirements: list[str]) -> set[str]:
    names: set[str] = set()
    for requirement in requirements:
        match = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)", requirement)
        assert match is not None, requirement
        names.add(re.sub(r"[-_.]+", "-", match.group(1)).lower())
    return names


def test_policy_no_new_runtime_dependency() -> None:
    project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))

    assert _requirement_names(project["project"]["dependencies"]) == RUNTIME_DEPENDENCIES


def test_policy_no_new_dev_dependency() -> None:
    project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    groups = project.get("dependency-groups", {})

    assert set(groups) == {"dev"}
    assert _requirement_names(groups["dev"]) == DEV_DEPENDENCIES


# --- AC9: CI Compose smoke test through the frontend proxy -----------------------------

EXTRACT_URL = re.compile(r"(?:localhost|127\.0\.0\.1):5173/api/extract\b")


def _extract_smoke_blocks() -> list[str]:
    jobs = _jobs(_workflow("ci.yml"))
    assert "compose" in jobs
    return [b for b in _run_blocks(_text(jobs["compose"])) if EXTRACT_URL.search(b)]


def test_ci_compose_job_posts_to_extract_through_frontend_proxy() -> None:
    assert EXTRACT_URL.search(_job_runs("ci.yml", "compose"))


def test_ci_compose_extract_smoke_sends_octet_stream() -> None:
    blocks = _extract_smoke_blocks()

    assert any(
        re.search(r"Content-Type:\s*application/octet-stream", b, re.IGNORECASE) for b in blocks
    )


def test_ci_compose_extract_smoke_posts_raw_body() -> None:
    blocks = _extract_smoke_blocks()

    assert any(
        re.search(r"(?:--data-binary|--data-raw|--data\b|\s-d\s|-X\s*POST|--request\s+POST)", b)
        for b in blocks
    )


def test_ci_compose_extract_smoke_sends_no_multipart_form() -> None:
    blocks = _extract_smoke_blocks()

    assert blocks
    for block in blocks:
        assert not re.search(r"(?:\s-F\s|--form\b|multipart)", block)


def test_ci_compose_extract_smoke_expects_kind_text() -> None:
    blocks = _extract_smoke_blocks()

    assert any('"kind":"text"' in b for b in blocks)


# --- Review round 1: single worker (the limiter counts per process) -------------------

DOCKERFILE = BACKEND / "Dockerfile"
COMPOSE_FILES = [
    BACKEND.parent / name
    for name in ("compose.yaml", "compose.yml", "docker-compose.yml", "docker-compose.yaml")
]


def _without_hash_comments(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


def _dockerfile_run_instructions() -> list[str]:
    """Every CMD and ENTRYPOINT instruction, with continuation lines joined."""
    text = _without_hash_comments(DOCKERFILE.read_text(encoding="utf-8"))
    joined = re.sub(r"\\\n", " ", text)
    return [
        line
        for line in joined.splitlines()
        if re.match(r"\s*(CMD|ENTRYPOINT)\b", line, re.IGNORECASE)
    ]


def test_policy_dockerfile_has_cmd_running_uvicorn() -> None:
    instructions = _dockerfile_run_instructions()

    assert any("uvicorn" in line for line in instructions), instructions


def test_policy_dockerfile_cmd_runs_exactly_one_worker() -> None:
    uvicorn_lines = [line for line in _dockerfile_run_instructions() if "uvicorn" in line]
    assert uvicorn_lines

    for line in uvicorn_lines:
        assert re.findall(r"--workers(?:=|\s+)(\S+)", line) == ["1"], line


def test_policy_dockerfile_does_not_set_web_concurrency() -> None:
    # uvicorn reads WEB_CONCURRENCY as the default number of workers.
    text = _without_hash_comments(DOCKERFILE.read_text(encoding="utf-8"))

    assert "WEB_CONCURRENCY" not in text


def test_policy_compose_has_no_workers_option() -> None:
    found = [p for p in COMPOSE_FILES if p.is_file()]
    assert len(found) == 1
    text = _without_hash_comments(found[0].read_text(encoding="utf-8"))

    assert "--workers" not in text
    assert "WEB_CONCURRENCY" not in text
