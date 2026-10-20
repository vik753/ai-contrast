"""Repository policy tests for S1-T3 (Compose), S1-T4 and S1-T4b (CI, Dependabot, Docker).

Plain text and regex checks only: no YAML library (no new dependency).
The checks use a small indentation-based block finder. It understands the
block style used in this repository (two-space indentation, block lists);
flow-style mappings such as ``permissions: {contents: read}`` are handled
where noted.

Comments are stripped (full-line and inline ``# ...`` outside quotes) before
any structural check. Command checks look only inside ``run:`` blocks, so a
command mentioned in a step name or a comment does not count.

Threats: T8 (supply chain), T4.6, T1/T3 (hardening of the local stack).
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"
DEPENDABOT = REPO_ROOT / ".github" / "dependabot.yml"
DOCKERFILE = REPO_ROOT / "backend" / "Dockerfile"
FRONTEND_DOCKERFILE = REPO_ROOT / "frontend" / "Dockerfile.dev"
COMPOSE_NAMES = ("compose.yaml", "compose.yml", "docker-compose.yml", "docker-compose.yaml")

SHA40 = re.compile(r"^[0-9a-f]{40}$")
USES_LINE = re.compile(r"^\s*(?:-\s+)?uses:\s*(?P<value>['\"]?[^\s'\"#]+['\"]?)(?P<rest>.*)$")
ACTION_REF = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:/[^@\s]+)?@(?P<ref>[^\s]+)$")
VERSION_COMMENT = re.compile(r"^\s+#\s*v\d")
ALLOWED_TRIGGERS = {"push", "pull_request", "schedule", "workflow_dispatch"}
DIGEST = re.compile(r"@sha256:[0-9a-f]{64}$")


# ---------------------------------------------------------------------------
# Tiny YAML-ish helpers
# ---------------------------------------------------------------------------


def _read(path: Path) -> str:
    assert path.is_file(), f"missing file: {path.relative_to(REPO_ROOT)}"
    return path.read_text(encoding="utf-8")


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _is_structural(line: str) -> bool:
    stripped = line.strip()
    return bool(stripped) and not stripped.startswith("#")


def _block(lines: list[str], key: str, indent: int) -> list[str] | None:
    """Lines nested under the first ``<indent spaces>key:`` line, or None.

    The key line itself is returned first, so inline values stay visible.
    """
    pattern = re.compile(rf"^ {{{indent}}}{re.escape(key)}:(?:\s|$)")
    for i, line in enumerate(lines):
        if pattern.match(line):
            body = [line]
            for nxt in lines[i + 1 :]:
                if _is_structural(nxt) and _indent(nxt) <= indent:
                    break
                body.append(nxt)
            return body
    return None


def _child_keys(block: list[str]) -> dict[str, list[str]]:
    """Direct child mappings of a block: key -> its lines (key line included)."""
    structural = [line for line in block[1:] if _is_structural(line)]
    if not structural:
        return {}
    child_indent = min(_indent(line) for line in structural)
    children: dict[str, list[str]] = {}
    key_re = re.compile(rf"^ {{{child_indent}}}([A-Za-z0-9_.-]+):(?:\s|$)")
    for line in block[1:]:
        match = key_re.match(line)
        if match:
            name = match.group(1)
            sub = _block(block, name, child_indent)
            assert sub is not None
            children[name] = sub
    return children


def _text(lines: list[str]) -> str:
    return "\n".join(lines)


def _strip_inline_comment(line: str) -> str:
    """Drop a YAML ``# comment`` that starts outside quotes after whitespace."""
    quote: str | None = None
    for i, char in enumerate(line):
        if quote:
            if char == quote:
                quote = None
        elif char in "'\"":
            quote = char
        elif char == "#" and (i == 0 or line[i - 1] in " \t"):
            return line[:i].rstrip()
    return line


def _without_comments(text: str) -> str:
    """Remove full-line and inline comments; keep line structure otherwise."""
    lines = []
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            continue
        lines.append(_strip_inline_comment(line))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Workflows
# ---------------------------------------------------------------------------


def _workflow_files() -> list[Path]:
    if not WORKFLOWS_DIR.is_dir():
        return []
    return sorted([*WORKFLOWS_DIR.glob("*.yml"), *WORKFLOWS_DIR.glob("*.yaml")])


def _workflow(name: str) -> str:
    return _read(WORKFLOWS_DIR / name)


def _jobs(text: str) -> dict[str, list[str]]:
    jobs = _block(text.splitlines(), "jobs", 0)
    assert jobs is not None, "workflow has no top-level jobs:"
    return _child_keys(jobs)


def _run_blocks(text: str, *, keep_shell_comments: bool = False) -> list[str]:
    """The shell content of every ``run:`` key (inline or block scalar).

    YAML comments outside the block are ignored. Shell comment lines inside
    the block are dropped for command-presence checks; pass
    ``keep_shell_comments=True`` for expression checks, because GitHub
    Actions expands ``${{ }}`` before the shell sees the comment.
    """
    lines = text.splitlines()
    blocks: list[str] = []
    run_re = re.compile(r"^(?P<indent>\s*)(?:-\s+)?run:\s*(?P<inline>.*)$")
    for i, line in enumerate(lines):
        if line.lstrip().startswith("#"):
            continue
        match = run_re.match(line)
        if not match:
            continue
        key_indent = len(match.group("indent"))
        inline = match.group("inline").strip()
        body = [] if re.fullmatch(r"[|>][+-]?\d*", inline) else [inline]
        for nxt in lines[i + 1 :]:
            if nxt.strip() and _indent(nxt) <= key_indent:
                break
            if keep_shell_comments or not nxt.lstrip().startswith("#"):
                body.append(nxt)
        blocks.append("\n".join(body))
    return blocks


def _job_runs(workflow: str, job: str) -> str:
    jobs = _jobs(_workflow(workflow))
    assert job in jobs, f"{workflow}: job {job!r} not found; jobs: {sorted(jobs)}"
    return "\n".join(_run_blocks(_text(jobs[job])))


def _steps_using(text: str, action: str) -> list[str]:
    """Text of every step whose ``uses:`` starts with ``action@``."""
    lines = text.splitlines()
    steps: list[str] = []
    for i, line in enumerate(lines):
        match = USES_LINE.match(line)
        if not match or not match.group("value").strip("'\"").startswith(action + "@"):
            continue
        start = i
        while start > 0 and not lines[start].lstrip().startswith("- "):
            start -= 1
        step_indent = _indent(lines[start])
        body = [lines[start]]
        for nxt in lines[start + 1 :]:
            if _is_structural(nxt) and (
                _indent(nxt) < step_indent
                or (_indent(nxt) == step_indent and nxt.lstrip().startswith("- "))
            ):
                break
            body.append(nxt)
        steps.append(_without_comments(_text(body)))
    return steps


def _triggers(text: str) -> set[str]:
    lines = _without_comments(text).splitlines()
    for key in ("on", '"on"', "'on'", "true"):
        block = _block(lines, key, 0)
        if block is None:
            continue
        inline = block[0].split(":", 1)[1].strip()
        if inline.startswith("["):
            return {t.strip(" '\"") for t in inline.strip("[]").split(",") if t.strip()}
        if inline:
            return {inline.strip("'\"")}
        names = set(_child_keys(block))
        structural = [line for line in block[1:] if _is_structural(line)]
        if structural:
            child_indent = min(_indent(line) for line in structural)
            item_re = re.compile(rf"^ {{{child_indent}}}-\s+([A-Za-z_]+)\s*$")
            names |= {m.group(1) for m in map(item_re.match, block[1:]) if m}
        return names
    msg = "workflow has no top-level on:"
    raise AssertionError(msg)


def test_workflows_ci_and_codeql_exist() -> None:
    names = {path.name for path in _workflow_files()}

    assert {"ci.yml", "codeql.yml"} <= names, sorted(names)


def test_workflows_every_uses_pinned_by_sha_with_version_comment() -> None:
    files = _workflow_files()
    assert files, "no workflow files"
    problems: list[str] = []
    found = 0
    for path in files:
        for number, line in enumerate(_read(path).splitlines(), start=1):
            match = USES_LINE.match(line)
            if not match:
                continue
            found += 1
            value = match.group("value").strip("'\"")
            where = f"{path.name}:{number}: {line.strip()}"
            if value.startswith("./"):
                continue  # local action in this repository
            ref = ACTION_REF.match(value)
            if not ref or not SHA40.match(ref.group("ref")):
                problems.append(f"not pinned by 40-hex SHA: {where}")
            elif not VERSION_COMMENT.match(match.group("rest")):
                problems.append(f"missing '# v...' version comment: {where}")
    assert found, "no uses: lines found"
    assert not problems, "\n".join(problems)


def test_workflows_top_level_permissions_contents_read() -> None:
    files = _workflow_files()
    assert files, "no workflow files"
    problems: list[str] = []
    for path in files:
        lines = _read(path).splitlines()
        block = _block(lines, "permissions", 0)
        if block is None:
            problems.append(f"{path.name}: no top-level permissions:")
            continue
        text = _without_comments(_text(block))
        if not re.search(r"\bcontents:\s*read\b", text):
            problems.append(f"{path.name}: top-level permissions lack 'contents: read'")
        if re.search(r"permissions:\s*(?:write-all|read-all)\b", text):
            problems.append(f"{path.name}: blanket permissions are not allowed")
    assert not problems, "\n".join(problems)


def test_workflows_top_level_permissions_grant_no_write() -> None:
    files = _workflow_files()
    assert files, "no workflow files"
    problems: list[str] = []
    for path in files:
        block = _block(_read(path).splitlines(), "permissions", 0)
        if block is not None and re.search(r":\s*write\b", _without_comments(_text(block))):
            problems.append(path.name)
    assert not problems, f"top-level write permission in: {problems}"


def test_workflows_no_pull_request_target() -> None:
    files = _workflow_files()
    assert files, "no workflow files"
    offenders = [
        path.name
        for path in files
        if re.search(r"\bpull_request_target\b", _without_comments(_read(path)))
    ]
    assert not offenders, offenders


def test_workflows_no_workflow_run_trigger() -> None:
    files = _workflow_files()
    assert files, "no workflow files"
    offenders = [
        path.name
        for path in files
        if re.search(r"\bworkflow_run\b", _without_comments(_read(path)))
    ]
    assert not offenders, offenders


def test_workflows_only_allowed_triggers() -> None:
    files = _workflow_files()
    assert files, "no workflow files"
    problems = {
        path.name: sorted(_triggers(_read(path)) - ALLOWED_TRIGGERS)
        for path in files
        if _triggers(_read(path)) - ALLOWED_TRIGGERS
    }
    assert not problems, problems


def test_workflows_no_expressions_inside_run_blocks() -> None:
    files = _workflow_files()
    assert files, "no workflow files"
    problems = [
        f"{path.name}: {line.strip()}"
        for path in files
        for block in _run_blocks(_read(path), keep_shell_comments=True)
        for line in block.splitlines()
        if "${{" in line
    ]
    assert not problems, "pass values through env: instead:\n" + "\n".join(problems)


def test_workflows_job_permissions_only_read_or_none() -> None:
    files = _workflow_files()
    assert files, "no workflow files"
    problems: list[str] = []
    for path in files:
        for job, lines in _jobs(_without_comments(_read(path))).items():
            child_indent = min(_indent(line) for line in lines[1:] if _is_structural(line))
            block = _block(lines, "permissions", child_indent)
            if block is None:
                continue
            inline = block[0].split(":", 1)[1].strip()
            if inline:
                if inline not in {"read-all", "{}"}:
                    problems.append(f"{path.name}/{job}: permissions: {inline}")
                continue
            for line in block[1:]:
                match = re.match(r"^\s*([a-z-]+):\s*(\S+)\s*$", line)
                if not match:
                    continue
                scope, level = match.groups()
                if level in {"read", "none"}:
                    continue
                if path.name == "codeql.yml" and (scope, level) == ("security-events", "write"):
                    continue
                problems.append(f"{path.name}/{job}: {scope}: {level}")
    assert not problems, problems


def test_workflows_checkout_steps_do_not_persist_credentials() -> None:
    files = _workflow_files()
    assert files, "no workflow files"
    problems: list[str] = []
    found = 0
    for path in files:
        for step in _steps_using(_read(path), "actions/checkout"):
            found += 1
            if not re.search(r"^\s*persist-credentials:\s*false\s*$", step, re.M):
                problems.append(f"{path.name}: {step.strip().splitlines()[0]}")
    assert found, "no actions/checkout steps found"
    assert not problems, problems


def test_ci_triggers_on_push_to_main_and_pull_request() -> None:
    on_block = _block(_without_comments(_workflow("ci.yml")).splitlines(), "on", 0)
    assert on_block is not None, "ci.yml has no top-level on:"
    text = _text(on_block)

    assert re.search(r"\bpull_request\b", text)
    assert re.search(r"\bpush\b", text)
    assert re.search(r"\bmain\b", text)


@pytest.mark.parametrize("job", ["backend", "frontend", "docker", "compose"])
def test_ci_has_job(job: str) -> None:
    assert job in _jobs(_workflow("ci.yml"))


@pytest.mark.parametrize(
    "command",
    [
        r"uv sync --locked",
        r"ruff check",
        r"ruff format --check",
        r"\bmypy\b",
        r"\bpytest\b",
        r"\bpip-audit\b",
    ],
)
def test_ci_backend_job_runs_command(command: str) -> None:
    assert re.search(command, _job_runs("ci.yml", "backend")), command


def test_ci_backend_job_pip_audit_uses_osv_source() -> None:
    runs = _job_runs("ci.yml", "backend")

    assert re.search(r"pip-audit[^\n]*(?:-s|--vulnerability-service)[ =]osv", runs)


@pytest.mark.parametrize(
    "command",
    [
        r"npm ci\b",
        r"npm run lint\b",
        r"npm run typecheck\b",
        r"npm (?:run )?test\b",
        r"npm run build\b",
        r"npm audit --audit-level[ =]high\b",
    ],
)
def test_ci_frontend_job_runs_command(command: str) -> None:
    assert re.search(command, _job_runs("ci.yml", "frontend")), command


@pytest.mark.parametrize("job", ["backend", "frontend"])
def test_ci_job_has_no_continue_on_error(job: str) -> None:
    jobs = _jobs(_without_comments(_workflow("ci.yml")))
    assert job in jobs

    assert not re.search(r"\bcontinue-on-error\b", _text(jobs[job]))


@pytest.mark.parametrize("job", ["backend", "frontend"])
def test_ci_job_run_blocks_do_not_swallow_failures(job: str) -> None:
    runs = _job_runs("ci.yml", job)

    assert not re.search(r"\|\|\s*(?:true\b|:(?:\s|$))", runs), runs


def test_ci_docker_job_builds_image_and_checks_health() -> None:
    runs = _job_runs("ci.yml", "docker")
    job = _without_comments(_text(_jobs(_workflow("ci.yml"))["docker"]))

    assert re.search(r"docker (?:buildx )?build\b", runs) or "docker/build-push-action" in job
    assert "/api/health" in runs


def test_ci_compose_job_validates_config() -> None:
    assert "docker compose config" in _job_runs("ci.yml", "compose")


def test_ci_compose_job_checks_health_through_frontend_proxy() -> None:
    runs = _job_runs("ci.yml", "compose")

    assert re.search(r"(?:localhost|127\.0\.0\.1):5173/api/health", runs)


# --- OpenTelemetry / telemetry SDK guard (S1-T4b policy AC9) ---------------

DENIED_PACKAGES = [
    "opentelemetry-sdk",
    "opentelemetry-exporter-otlp",
    "opentelemetry-exporter-otlp-proto-http",
    "opentelemetry-distro",
    "logfire",
    "sentry-sdk",
]
ALLOWED_PACKAGES = ["opentelemetry-api", "opentelemetry-semantic-conventions", "fastapi"]


def _otel_guard_block() -> str:
    blocks = [b for b in _run_blocks(_workflow("ci.yml")) if "uv.lock" in b and "grep" in b]
    assert len(blocks) >= 1, "no run block greps uv.lock"
    guards = [b for b in blocks if "opentelemetry" in b]
    assert guards, "no run block greps uv.lock for opentelemetry packages"
    return guards[0]


def _otel_deny_regex() -> re.Pattern[str]:
    block = _otel_guard_block()
    match = re.search(
        r"grep\s+(?:-[A-Za-z]+\s+)*(?:-e\s+)?(?P<q>['\"])(?P<pattern>.+?)(?P=q)", block
    )
    assert match, f"cannot find a quoted grep pattern in:\n{block}"
    return re.compile(match.group("pattern"))


def test_ci_otel_guard_exits_non_zero_on_match() -> None:
    block = _otel_guard_block()

    assert re.search(r"\bexit\s+[1-9]|^\s*!\s*grep\b|grep[^\n]*&&\s*exit\s+[1-9]", block, re.M), (
        block
    )


@pytest.mark.parametrize("package", DENIED_PACKAGES)
def test_ci_otel_guard_regex_matches_denied_package(package: str) -> None:
    lock_line = f'name = "{package}"'

    assert _otel_deny_regex().search(lock_line), lock_line


@pytest.mark.parametrize("package", ALLOWED_PACKAGES)
def test_ci_otel_guard_regex_allows_api_package(package: str) -> None:
    lock_line = f'name = "{package}"'

    assert not _otel_deny_regex().search(lock_line), lock_line


# --- setup-uv version (S1-T4b policy AC8) ---------------------------------


def _dockerfile_uv_tag() -> str:
    images = [
        image for image, _ in _from_lines(DOCKERFILE) if image.startswith("ghcr.io/astral-sh/uv")
    ]
    assert len(images) == 1, images
    match = re.match(r"^ghcr\.io/astral-sh/uv:(\d+\.\d+\.\d+)", images[0])
    assert match, images[0]
    return match.group(1)


def test_ci_setup_uv_version_matches_dockerfile_uv_tag() -> None:
    tag = _dockerfile_uv_tag()
    steps = [
        step
        for path in _workflow_files()
        for step in _steps_using(_read(path), "astral-sh/setup-uv")
    ]
    assert steps, "no astral-sh/setup-uv steps"
    versions = [
        m.group(1) if (m := re.search(r"^\s*version:\s*['\"]?([^\s'\"]+)", step, re.M)) else None
        for step in steps
    ]

    assert versions == [tag] * len(steps), (tag, versions)


# --- CodeQL ------------------------------------------------------------------


def _codeql_languages() -> set[str]:
    """Values of every ``language:``/``languages:`` key (inline, flow or block list)."""
    lines = _without_comments(_workflow("codeql.yml")).splitlines()
    found: set[str] = set()
    key_re = re.compile(r"^(\s*)(?:-\s+)?languages?:\s*(.*)$")
    for i, line in enumerate(lines):
        match = key_re.match(line)
        if not match:
            continue
        indent, inline = len(match.group(1)), match.group(2).strip()
        if inline and "${{" not in inline:
            found |= {t.strip(" '\"") for t in re.split(r"[,\s]+", inline.strip("[]")) if t.strip()}
        for nxt in lines[i + 1 :]:
            if _is_structural(nxt) and _indent(nxt) <= indent:
                break
            item = re.match(r"^\s*-\s+['\"]?([\w-]+)['\"]?\s*$", nxt)
            if item:
                found.add(item.group(1))
    found.discard("")
    return found


@pytest.mark.parametrize("language", ["python", "javascript-typescript", "actions"])
def test_codeql_covers_language(language: str) -> None:
    languages = _codeql_languages()

    assert language in languages, languages


def test_codeql_runs_on_push_pull_request_and_schedule() -> None:
    on_block = _block(_without_comments(_workflow("codeql.yml")).splitlines(), "on", 0)
    assert on_block is not None, "codeql.yml has no top-level on:"
    text = _text(on_block)

    assert re.search(r"\bpush\b", text)
    assert re.search(r"\bpull_request\b", text)
    assert re.search(r"\bschedule\b", text)
    assert re.search(r"\bcron\b", text)


def test_codeql_job_grants_security_events_write() -> None:
    text = _without_comments(_workflow("codeql.yml"))

    assert re.search(r"security-events:\s*write\b", text)


# ---------------------------------------------------------------------------
# Dependabot
# ---------------------------------------------------------------------------

DEPENDABOT_REQUIRED = [
    ("uv", "/backend"),
    ("npm", "/frontend"),
    ("github-actions", "/"),
    ("docker", "/backend"),
    ("docker-compose", "/"),
]
PINNED_BASE_IMAGES = ["python", "node", "ghcr.io/astral-sh/uv"]


def _dependabot_updates() -> list[tuple[str, str]]:
    """(ecosystem, block text) for every update entry, comments removed."""
    text = _without_comments(_read(DEPENDABOT))
    parts = re.split(r"^\s*-\s+package-ecosystem:", text, flags=re.MULTILINE)
    return [(part.split("\n", 1)[0].strip().strip("'\""), part) for part in parts[1:]]


def _dependabot_blocks(ecosystem: str) -> list[str]:
    blocks = [block for name, block in _dependabot_updates() if name == ecosystem]
    assert blocks, f"dependabot has no {ecosystem!r} entry"
    return blocks


def _directories(block: str) -> set[str]:
    found = set(re.findall(r"^\s*directory:\s*['\"]?([^\s'\"]+)", block, re.M))
    lines = block.splitlines()
    dirs = _block(
        lines, "directories", min(_indent(line) for line in lines[1:] if _is_structural(line))
    )
    if dirs is not None:
        text = _text(dirs)
        found |= set(re.findall(r"['\"]?(/[^\s'\",\]]*)['\"]?", text))
    return found


@pytest.mark.parametrize(("ecosystem", "directory"), DEPENDABOT_REQUIRED)
def test_dependabot_covers_ecosystem_directory(ecosystem: str, directory: str) -> None:
    directories = set().union(*(_directories(b) for b in _dependabot_blocks(ecosystem)))

    assert directory in directories, (ecosystem, directories)


def test_dependabot_docker_covers_frontend_when_frontend_dockerfile_exists() -> None:
    if not FRONTEND_DOCKERFILE.is_file():
        pytest.skip("no frontend/Dockerfile.dev")
    directories = set().union(*(_directories(b) for b in _dependabot_blocks("docker")))

    assert "/frontend" in directories, directories


@pytest.mark.parametrize("ecosystem", sorted({e for e, _ in DEPENDABOT_REQUIRED}))
def test_dependabot_ecosystem_has_cooldown_seven_days(ecosystem: str) -> None:
    for block in _dependabot_blocks(ecosystem):
        assert re.search(r"^\s*cooldown:\s*$", block, re.M), block
        assert re.search(r"default-days:\s*7\b", block), block


@pytest.mark.parametrize("ecosystem", sorted({e for e, _ in DEPENDABOT_REQUIRED}))
def test_dependabot_ecosystem_weekly(ecosystem: str) -> None:
    for block in _dependabot_blocks(ecosystem):
        assert re.search(r"interval:\s*['\"]?weekly['\"]?", block), block


def _ignore_entries(ecosystem: str | None = None, directory: str | None = None) -> dict[str, str]:
    """dependency-name -> text of its ignore entry.

    Without arguments all update blocks are searched; otherwise only blocks of
    the given ecosystem (and directory).
    """
    entries: dict[str, str] = {}
    for name, block in _dependabot_updates():
        if ecosystem is not None and name != ecosystem:
            continue
        if directory is not None and directory not in _directories(block):
            continue
        lines = block.splitlines()
        for i, line in enumerate(lines):
            match = re.match(r"^(\s*)-\s+dependency-name:\s*['\"]?([^\s'\"]+)", line)
            if not match:
                continue
            indent = len(match.group(1))
            body = [line]
            for nxt in lines[i + 1 :]:
                if _is_structural(nxt) and _indent(nxt) <= indent:
                    break
                body.append(nxt)
            entries.setdefault(match.group(2), "")
            entries[match.group(2)] += _text(body) + "\n"
    return entries


@pytest.mark.parametrize("image", PINNED_BASE_IMAGES)
def test_dependabot_ignores_major_and_minor_updates_for_base_image(image: str) -> None:
    entries = _ignore_entries()
    assert image in entries, f"no ignore rule for {image!r}; rules: {sorted(entries)}"

    assert "version-update:semver-major" in entries[image]
    assert "version-update:semver-minor" in entries[image]


# --- S1-T6: names Dependabot really uses, and npm majors -------------------


def test_dependabot_docker_ignores_major_and_minor_for_uv_dependabot_name() -> None:
    # Dependabot names the ghcr.io image "astral-sh/uv" (see PR #8), so a rule
    # for "ghcr.io/astral-sh/uv" alone does not match.
    entries = _ignore_entries("docker")
    assert "astral-sh/uv" in entries, f"docker ignore rules: {sorted(entries)}"

    assert "version-update:semver-major" in entries["astral-sh/uv"]
    assert "version-update:semver-minor" in entries["astral-sh/uv"]


def test_dependabot_npm_frontend_ignores_majors_for_all_dependencies() -> None:
    entries = _ignore_entries("npm", "/frontend")
    assert "*" in entries, f"npm /frontend ignore rules: {sorted(entries)}"

    assert "version-update:semver-major" in entries["*"]


def test_dependabot_npm_wildcard_rule_keeps_minor_and_patch_updates() -> None:
    entries = _ignore_entries("npm", "/frontend")
    assert "*" in entries, f"npm /frontend ignore rules: {sorted(entries)}"

    assert "version-update:semver-minor" not in entries["*"]
    assert "version-update:semver-patch" not in entries["*"]


# ---------------------------------------------------------------------------
# Dockerfiles
# ---------------------------------------------------------------------------

DOCKERFILES = [DOCKERFILE, FRONTEND_DOCKERFILE]


def _dockerfile_ids() -> list[str]:
    return [str(path.relative_to(REPO_ROOT)) for path in DOCKERFILES]


def _from_lines(path: Path = DOCKERFILE) -> list[tuple[str, str | None]]:
    """(image, stage alias) for every FROM instruction."""
    result: list[tuple[str, str | None]] = []
    for line in _read(path).splitlines():
        match = re.match(r"^\s*FROM\s+(?:--platform=\S+\s+)?(\S+)(?:\s+AS\s+(\S+))?", line, re.I)
        if match:
            result.append((match.group(1), match.group(2)))
    return result


def test_frontend_dev_dockerfile_exists() -> None:
    assert FRONTEND_DOCKERFILE.is_file()


@pytest.mark.parametrize("path", DOCKERFILES, ids=_dockerfile_ids())
def test_dockerfile_every_from_image_pinned_by_digest(path: Path) -> None:
    froms = _from_lines(path)
    assert froms, "no FROM lines"
    stages: set[str] = set()
    problems: list[str] = []
    for image, alias in froms:
        if image.lower() not in stages and not DIGEST.search(image):
            problems.append(image)
        if alias:
            stages.add(alias.lower())
    assert not problems, f"FROM without @sha256:<64 hex>: {problems}"


@pytest.mark.parametrize("path", DOCKERFILES, ids=_dockerfile_ids())
def test_dockerfile_from_options_are_stage_alias_or_pinned_image(path: Path) -> None:
    """``COPY --from=`` and ``RUN --mount=...,from=...`` (bind, cache) sources."""
    text = "\n".join(line for line in _read(path).splitlines() if not line.lstrip().startswith("#"))
    stages = {alias.lower() for _, alias in _from_lines(path) if alias}
    values = re.findall(r"(?<![\w-])(?:--)?from=([^\s,]+)", text)
    problems = [
        value
        for value in (v.strip("'\"") for v in values)
        if value.lower() not in stages and not value.isdigit() and not DIGEST.search(value)
    ]
    assert not problems, f"from= must name a stage or a digest-pinned image: {problems}"


@pytest.mark.parametrize("path", DOCKERFILES, ids=_dockerfile_ids())
def test_dockerfile_syntax_directive_absent_or_pinned(path: Path) -> None:
    directives = re.findall(r"^#\s*syntax\s*=\s*(\S+)", _read(path), re.M | re.I)
    problems = [value for value in directives if not DIGEST.search(value)]

    assert not problems, f"unpinned # syntax= directive: {problems}"


def test_dockerfile_python_slim_digest_same_in_all_stages() -> None:
    images = [image for image, _ in _from_lines() if image.startswith("python:3.13-slim")]

    assert len(images) >= 2, images  # builder and runtime
    assert len(set(images)) == 1, images


def test_dockerfile_uv_image_keeps_version_tag_and_digest() -> None:
    images = [image for image, _ in _from_lines() if image.startswith("ghcr.io/astral-sh/uv")]

    assert len(images) == 1, images
    assert re.match(r"^ghcr\.io/astral-sh/uv:\d+\.\d+\.\d+@sha256:[0-9a-f]{64}$", images[0])


def test_frontend_dev_dockerfile_final_user_is_not_root() -> None:
    users = re.findall(r"^\s*USER\s+(\S+)", _read(FRONTEND_DOCKERFILE), re.M | re.I)

    assert users, "frontend/Dockerfile.dev sets no USER"
    assert not _is_root_user(users[-1]), users[-1]


# ---------------------------------------------------------------------------
# Compose
# ---------------------------------------------------------------------------


def _is_root_user(value: str) -> bool:
    uid = value.strip("'\"").split(":", 1)[0]
    return uid in {"", "0", "root"}


def _compose_path() -> Path:
    found = [REPO_ROOT / name for name in COMPOSE_NAMES if (REPO_ROOT / name).is_file()]
    assert len(found) == 1, f"expected exactly one Compose file at repo root, found {found}"
    return found[0]


def _compose_text() -> str:
    return _without_comments(_read(_compose_path()))


def _services() -> dict[str, list[str]]:
    block = _block(_compose_text().splitlines(), "services", 0)
    assert block is not None, "Compose file has no services:"
    return _child_keys(block)


def _service(name: str) -> str:
    services = _services()
    assert name in services, f"service {name!r} not found; services: {sorted(services)}"
    return _text(services[name])


def _service_key(lines: list[str], key: str) -> list[str] | None:
    child_indent = min(_indent(line) for line in lines[1:] if _is_structural(line))
    return _block(lines, key, child_indent)


def _service_section(service: str, key: str) -> str:
    block = _service_key(_service(service).splitlines(), key)
    assert block is not None, f"service {service!r} has no {key}:"
    return _text(block)


def _inline_value(service: str, key: str) -> str | None:
    block = _service_key(_service(service).splitlines(), key)
    if block is None:
        return None
    return block[0].split(":", 1)[1].strip().strip("'\"")


def test_compose_file_exists_at_repo_root() -> None:
    _compose_path()


@pytest.mark.parametrize("service", ["backend", "frontend"])
def test_compose_has_service(service: str) -> None:
    assert service in _services()


@pytest.mark.parametrize("service", ["backend", "frontend"])
def test_compose_service_read_only_root_filesystem(service: str) -> None:
    assert _inline_value(service, "read_only") == "true"


@pytest.mark.parametrize("service", ["backend", "frontend"])
def test_compose_service_tmpfs_for_tmp_noexec_with_size_cap(service: str) -> None:
    tmpfs = _service_section(service, "tmpfs")
    tmp_entries = [line for line in tmpfs.splitlines() if re.search(r"(?:^|[\s\"'-])/tmp\b", line)]

    assert tmp_entries, tmpfs
    assert any("noexec" in line and "size=" in line for line in tmp_entries), tmp_entries


@pytest.mark.parametrize("service", ["backend", "frontend"])
def test_compose_service_drops_all_capabilities(service: str) -> None:
    cap_drop = _service_section(service, "cap_drop")

    assert re.search(r"\bALL\b", cap_drop), cap_drop


@pytest.mark.parametrize("service", ["backend", "frontend"])
def test_compose_service_no_new_privileges(service: str) -> None:
    security_opt = _service_section(service, "security_opt")

    assert re.search(r"no-new-privileges:\s*true", security_opt), security_opt


def test_compose_backend_memory_limit_512m() -> None:
    assert (_inline_value("backend", "mem_limit") or "").lower() in {"512m", "512mb"}


def test_compose_backend_environment_development() -> None:
    environment = _service_section("backend", "environment")

    assert re.search(r"ENVIRONMENT(?:=|:\s*)['\"]?development\b", environment), environment


def test_compose_backend_allowed_origins_local_frontend() -> None:
    environment = _service_section("backend", "environment")

    assert re.search(r"ALLOWED_ORIGINS(?:=|:\s*)['\"]?[^\n]*http://localhost:5173", environment), (
        environment
    )


def test_compose_frontend_runs_as_non_root_user() -> None:
    user = _inline_value("frontend", "user")
    if user is None:
        # Fall back to the image's final USER when Compose builds Dockerfile.dev.
        assert "Dockerfile.dev" in _service("frontend"), "frontend sets no user:"
        users = re.findall(r"^\s*USER\s+(\S+)", _read(FRONTEND_DOCKERFILE), re.M | re.I)
        assert users, "frontend runs as root: no user: and no USER"
        user = users[-1]

    assert not _is_root_user(user), user


SERVICE_FORBIDDEN = {
    "privileged": r"^\s+privileged:\s*['\"]?true",
    "network_mode host": r"^\s+network_mode:\s*['\"]?host\b",
    "pid host": r"^\s+pid:\s*['\"]?host\b",
    "cap_add": r"^\s+cap_add:",
    "docker.sock": r"docker\.sock",
}


@pytest.mark.parametrize("rule", sorted(SERVICE_FORBIDDEN))
def test_compose_no_service_uses_forbidden_option(rule: str) -> None:
    pattern = re.compile(SERVICE_FORBIDDEN[rule], re.M)
    offenders = [name for name, lines in _services().items() if pattern.search(_text(lines))]

    assert not offenders, f"{rule}: {offenders}"


def test_compose_every_image_pinned_by_digest() -> None:
    problems = []
    for name, lines in _services().items():
        image = _service_key(lines, "image")
        if image is None:
            continue
        value = image[0].split(":", 1)[1].strip().strip("'\"")
        if not DIGEST.search(value):
            problems.append(f"{name}: {value}")
    assert not problems, problems


def test_compose_every_published_port_bound_to_localhost() -> None:
    problems: list[str] = []
    published = 0
    for name, lines in _services().items():
        ports = _service_key(lines, "ports")
        if ports is None:
            continue
        text = _text(ports)
        short = re.findall(r"^\s*-\s+['\"]?([^\s'\"]+)['\"]?\s*$", text, re.M)
        for entry in short:
            published += 1
            if not entry.startswith("127.0.0.1:"):
                problems.append(f"{name}: {entry}")
        targets = len(re.findall(r"^\s*-?\s*target:", text, re.M))
        bound = len(re.findall(r"host_ip:\s*['\"]?127\.0\.0\.1['\"]?\s*$", text, re.M))
        published += targets
        if targets != bound:
            problems.append(f"{name}: long-syntax port without host_ip 127.0.0.1")
        if re.match(r"^\s*ports:\s*\[", ports[0]):
            problems.append(f"{name}: flow-style ports list is not supported by this policy")
    assert published, "no published ports found"
    assert not problems, problems


def test_compose_frontend_proxy_target_is_backend_service() -> None:
    environment = _service_section("frontend", "environment")

    assert re.search(
        r"VITE_API_PROXY_TARGET(?:=|:\s*)['\"]?http://backend:8000['\"]?\s*$", environment, re.M
    ), environment


def test_compose_frontend_installs_with_npm_ci_ignore_scripts() -> None:
    frontend = _service("frontend")

    assert re.search(r"npm ci\b[^\n]*--ignore-scripts", frontend), frontend


def test_compose_frontend_runs_dev_server() -> None:
    assert "npm run dev" in _service("frontend")


def test_compose_does_not_use_env_file() -> None:
    assert not re.search(r"^\s*env_file:", _compose_text(), re.M)


# ---------------------------------------------------------------------------
# Git: no committed .env files (S1-T4b policy AC10)
# ---------------------------------------------------------------------------


def _tracked_files() -> list[str]:
    git = shutil.which("git")
    if git is None:
        pytest.skip("git is not available")
    result = subprocess.run(  # noqa: S603 - fixed arguments
        [git, "ls-files", "-z"],
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
        timeout=30,
    )
    if result.returncode != 0:
        pytest.skip("not a git checkout")
    return [name for name in result.stdout.decode("utf-8", "replace").split("\0") if name]


def test_git_tracks_no_dotenv_files() -> None:
    offenders = [
        name
        for name in _tracked_files()
        if Path(name).name.startswith(".env") and Path(name).name != ".env.example"
    ]
    assert not offenders, offenders
