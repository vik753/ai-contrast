# syntax=docker/dockerfile:1
#
# AI Contrast backend image.
# Build:  docker build -t ai-contrast-backend backend/
# Run:    docker run --rm -p 8000:8000 ai-contrast-backend
#
# TODO(S1-T4): pin both base images by digest (`image:tag@sha256:...`) and let
# Dependabot (`docker` ecosystem) update them.

# uv binary only; pinned to the version used to create uv.lock.
FROM ghcr.io/astral-sh/uv:0.11.32 AS uv

# ---- builder: resolve and install locked runtime dependencies into /app/.venv ----
FROM python:3.13-slim AS builder

COPY --from=uv /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PYTHON=/usr/local/bin/python3.13 \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

# Dependencies first (better layer cache). `--locked` fails if uv.lock is out of date;
# uv.lock pins every package with hashes. No dev dependencies in the image.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev

COPY log_config.json ./
COPY app ./app
RUN python -m compileall -q app

# ---- runtime: no uv, no build tools, non-root ----
FROM python:3.13-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:${PATH}"

RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app

WORKDIR /app

# Files stay owned by root: the app user can read but not modify the code.
COPY --from=builder /app /app

USER 10001:10001

EXPOSE 8000

# - `--no-access-log`: our own access log middleware writes one safe line per request.
# - `--log-config`: root handler to stderr, so `ai_contrast.*` loggers are printed.
# - `--no-server-header`: do not advertise the server software.
# - `--no-proxy-headers`: X-Forwarded-* are not trusted for now. Nothing uses the client
#   IP yet. When per-IP rate limiting arrives, enable proxy headers with
#   `--forwarded-allow-ips` restricted to the hosting proxy, and document it.
# `sh -c` expands $PORT (set by the host, for example Render); `exec` makes uvicorn PID 1.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port \"${PORT:-8000}\" --no-access-log --no-proxy-headers --no-server-header --log-config log_config.json"]
