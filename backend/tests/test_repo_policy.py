"""Repository policy tests for S1-T3 (Compose) and S1-T4 (CI, Dependabot, Docker).

Plain text and regex checks only: no YAML library (no new dependency).
The checks use a small indentation-based block finder. It understands the
block style used in this repository (two-space indentation, block lists);
flow-style mappings such as ``permissions: {contents: read}`` are handled
where noted.

Threats: T8 (supply chain), T1/T3 (hardening of the local stack).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"
DEPENDABOT = REPO_ROOT / ".github" / "dependabot.yml"
DOCKERFILE = REPO_ROOT / "backend" / "Dockerfile"
COMPOSE_NAMES = ("compose.yaml", "compose.yml", "docker-compose.yml", "docker-compose.yaml")

SHA40 = re.compile(r"^[0-9a-f]{40}$")
USES_LINE = re.compile(r"^\s*(?:-\s+)?uses:\s*(?P<value>['\"]?[^\s'\"#]+['\"]?)(?P<rest>.*)$")
ACTION_REF = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:/[^@\s]+)?@(?P<ref>[^\s]+)$")
VERSION_COMMENT = re.compile(r"^\s+#\s*v\d")
EVENT_EXPR = re.compile(r"\$\{\{\s*github\.(?:event\.|head_ref\b)")
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


def _without_comments(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


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


def _job_text(workflow: str, job: str) -> str:
    jobs = _jobs(_workflow(workflow))
    assert job in jobs, f"{workflow}: job {job!r} not found; jobs: {sorted(jobs)}"
    return _without_comments(_text(jobs[job]))


def _run_blocks(text: str) -> list[str]:
    """The content of every ``run:`` key (inline or block scalar)."""
    lines = text.splitlines()
    blocks: list[str] = []
    run_re = re.compile(r"^(?P<indent>\s*)(?:-\s+)?run:\s*(?P<inline>.*)$")
    for i, line in enumerate(lines):
        match = run_re.match(line)
        if not match:
            continue
        key_indent = len(match.group("indent"))
        body = [match.group("inline")]
        for nxt in lines[i + 1 :]:
            if nxt.strip() and _indent(nxt) <= key_indent:
                break
            body.append(nxt)
        blocks.append("\n".join(body))
    return blocks


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


def test_workflows_no_event_expressions_inside_run_blocks() -> None:
    files = _workflow_files()
    assert files, "no workflow files"
    problems = [
        f"{path.name}: {block.strip().splitlines()[0] if block.strip() else ''}"
        for path in files
        for block in _run_blocks(_read(path))
        if EVENT_EXPR.search(block)
    ]
    assert not problems, "use env: variables instead:\n" + "\n".join(problems)


def test_ci_triggers_on_push_to_main_and_pull_request() -> None:
    on_block = _block(_workflow("ci.yml").splitlines(), "on", 0)
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
    assert re.search(command, _job_text("ci.yml", "backend")), command


def test_ci_backend_job_pip_audit_uses_osv_source() -> None:
    text = _job_text("ci.yml", "backend")

    assert re.search(r"pip-audit[^\n]*(?:-s|--vulnerability-service)[ =]osv", text)


def test_ci_rejects_opentelemetry_sdk_and_exporters_in_lock() -> None:
    text = _without_comments(_workflow("ci.yml"))
    otel_lines = [line for line in text.splitlines() if "opentelemetry" in line]

    assert any("sdk" in line for line in otel_lines), otel_lines
    assert any("exporter" in line for line in otel_lines), otel_lines
    assert "uv.lock" in text


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
    assert re.search(command, _job_text("ci.yml", "frontend")), command


def test_ci_docker_job_builds_image_and_checks_health() -> None:
    text = _job_text("ci.yml", "docker")

    assert re.search(r"docker (?:buildx )?build\b|docker/build-push-action", text)
    assert "/api/health" in text


def test_ci_compose_job_validates_config() -> None:
    assert "docker compose config" in _job_text("ci.yml", "compose")


def test_ci_compose_job_checks_health_through_frontend_proxy() -> None:
    text = _job_text("ci.yml", "compose")

    assert re.search(r"(?:localhost|127\.0\.0\.1):5173/api/health", text)


def test_codeql_covers_python_and_javascript_typescript() -> None:
    text = _without_comments(_workflow("codeql.yml"))

    assert re.search(r"\bpython\b", text)
    assert "javascript-typescript" in text


def test_codeql_runs_on_push_pull_request_and_schedule() -> None:
    on_block = _block(_workflow("codeql.yml").splitlines(), "on", 0)
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

DEPENDABOT_ECOSYSTEMS = {
    "uv": "/backend",
    "npm": "/frontend",
    "github-actions": "/",
    "docker": "/backend",
}


def _dependabot_updates() -> dict[str, str]:
    text = _without_comments(_read(DEPENDABOT))
    parts = re.split(r"^\s*-\s+package-ecosystem:", text, flags=re.MULTILINE)
    updates: dict[str, str] = {}
    for part in parts[1:]:
        name = part.split("\n", 1)[0].strip().strip("'\"")
        updates[name] = part
    return updates


@pytest.mark.parametrize("ecosystem", sorted(DEPENDABOT_ECOSYSTEMS))
def test_dependabot_covers_ecosystem(ecosystem: str) -> None:
    assert ecosystem in _dependabot_updates()


@pytest.mark.parametrize("ecosystem", sorted(DEPENDABOT_ECOSYSTEMS))
def test_dependabot_ecosystem_directory(ecosystem: str) -> None:
    block = _dependabot_updates()[ecosystem]
    directory = DEPENDABOT_ECOSYSTEMS[ecosystem]

    assert re.search(rf"director(?:y|ies):\s*['\"]?{re.escape(directory)}['\"]?\s*$", block, re.M)


@pytest.mark.parametrize("ecosystem", sorted(DEPENDABOT_ECOSYSTEMS))
def test_dependabot_ecosystem_has_cooldown_seven_days(ecosystem: str) -> None:
    block = _dependabot_updates()[ecosystem]

    assert re.search(r"^\s*cooldown:\s*$", block, re.M)
    assert re.search(r"default-days:\s*7\b", block)


@pytest.mark.parametrize("ecosystem", sorted(DEPENDABOT_ECOSYSTEMS))
def test_dependabot_ecosystem_weekly(ecosystem: str) -> None:
    block = _dependabot_updates()[ecosystem]

    assert re.search(r"interval:\s*['\"]?weekly['\"]?", block)


# ---------------------------------------------------------------------------
# Dockerfile
# ---------------------------------------------------------------------------


def _from_lines() -> list[tuple[str, str | None]]:
    """(image, stage alias) for every FROM instruction."""
    result: list[tuple[str, str | None]] = []
    for line in _read(DOCKERFILE).splitlines():
        match = re.match(r"^\s*FROM\s+(?:--platform=\S+\s+)?(\S+)(?:\s+AS\s+(\S+))?", line, re.I)
        if match:
            result.append((match.group(1), match.group(2)))
    return result


def test_dockerfile_every_from_image_pinned_by_digest() -> None:
    froms = _from_lines()
    assert froms, "no FROM lines"
    stages: set[str] = set()
    problems: list[str] = []
    for image, alias in froms:
        if image.lower() not in stages and not DIGEST.search(image):
            problems.append(image)
        if alias:
            stages.add(alias.lower())
    assert not problems, f"FROM without @sha256:<64 hex>: {problems}"


def test_dockerfile_python_slim_digest_same_in_all_stages() -> None:
    images = [image for image, _ in _from_lines() if image.startswith("python:3.13-slim")]

    assert len(images) >= 2, images  # builder and runtime
    assert len(set(images)) == 1, images


def test_dockerfile_uv_image_keeps_version_tag_and_digest() -> None:
    images = [image for image, _ in _from_lines() if image.startswith("ghcr.io/astral-sh/uv")]

    assert len(images) == 1, images
    assert re.match(r"^ghcr\.io/astral-sh/uv:\d+\.\d+\.\d+@sha256:[0-9a-f]{64}$", images[0])


# ---------------------------------------------------------------------------
# Compose
# ---------------------------------------------------------------------------


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


def _service_section(service: str, key: str) -> str:
    lines = _service(service).splitlines()
    child_indent = min(_indent(line) for line in lines[1:] if _is_structural(line))
    block = _block(lines, key, child_indent)
    assert block is not None, f"service {service!r} has no {key}:"
    return _text(block)


def test_compose_file_exists_at_repo_root() -> None:
    _compose_path()


@pytest.mark.parametrize("service", ["backend", "frontend"])
def test_compose_has_service(service: str) -> None:
    assert service in _services()


def test_compose_backend_read_only_root_filesystem() -> None:
    assert re.search(r"^\s+read_only:\s*true\s*$", _service("backend"), re.M)


def test_compose_backend_tmpfs_for_tmp_noexec_with_size_cap() -> None:
    tmpfs = _service_section("backend", "tmpfs")
    tmp_entries = [line for line in tmpfs.splitlines() if re.search(r"(?:^|[\s\"'-])/tmp\b", line)]

    assert tmp_entries, tmpfs
    assert any("noexec" in line and "size=" in line for line in tmp_entries), tmp_entries


def test_compose_backend_drops_all_capabilities() -> None:
    cap_drop = _service_section("backend", "cap_drop")

    assert re.search(r"\bALL\b", cap_drop), cap_drop


def test_compose_backend_no_new_privileges() -> None:
    security_opt = _service_section("backend", "security_opt")

    assert re.search(r"no-new-privileges:\s*true", security_opt), security_opt


def test_compose_backend_environment_development() -> None:
    environment = _service_section("backend", "environment")

    assert re.search(r"ENVIRONMENT(?:=|:\s*)['\"]?development\b", environment), environment


def test_compose_backend_allowed_origins_local_frontend() -> None:
    environment = _service_section("backend", "environment")

    assert re.search(r"ALLOWED_ORIGINS(?:=|:\s*)['\"]?[^\n]*http://localhost:5173", environment), (
        environment
    )


def test_compose_backend_not_privileged_and_no_host_network() -> None:
    backend = _service("backend")

    assert not re.search(r"privileged:\s*true", backend)
    assert not re.search(r"network_mode:\s*['\"]?host", backend)


def test_compose_every_published_port_bound_to_localhost() -> None:
    problems: list[str] = []
    published = 0
    for name, lines in _services().items():
        child_indent = min(_indent(line) for line in lines[1:] if _is_structural(line))
        ports = _block(lines, "ports", child_indent)
        if ports is None:
            continue
        text = _text(ports)
        short = re.findall(r"^\s*-\s+['\"]?([^\s'\"]+)['\"]?\s*$", text, re.M)
        for entry in short:
            published += 1
            if not entry.startswith("127.0.0.1:"):
                problems.append(f"{name}: {entry}")
        targets = len(re.findall(r"^\s*-?\s*target:", text, re.M))
        bound = len(re.findall(r"host_ip:\s*['\"]?127\.0\.0\.1['\"]?", text))
        published += targets
        if targets != bound:
            problems.append(f"{name}: long-syntax port without host_ip 127.0.0.1")
        inline = re.match(r"^\s*ports:\s*\[(.*)\]", ports[0])
        if inline:
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


def test_compose_no_dotenv_file_committed() -> None:
    assert not (REPO_ROOT / ".env").exists()
