# AI Contrast backend image.
# Build:  docker build -t ai-contrast-backend backend/
# Run:    docker run --rm -p 127.0.0.1:8000:8000 \
#           -e ALLOWED_ORIGINS=https://app.example ai-contrast-backend
#         (production mode by default; ALLOWED_ORIGINS with https origins is required)
#
# Base images are pinned by tag and multi-arch index digest; Dependabot (`docker`
# ecosystem) updates them. Keep the same Python digest in the builder and runtime.

# uv binary only; pinned to the version used to create uv.lock.
FROM ghcr.io/astral-sh/uv:0.11.33@sha256:77280f2f771df71f90786c314fe1bbc1e023feac652969bbf139c280babf2eb7 AS uv

# ---- builder: resolve and install locked runtime dependencies into /app/.venv ----
FROM python:3.13-slim@sha256:70729b46c69b4f1e97c4822c1af3df53a1476cf5ddc6c087c0c10bc3a5678c2f AS builder

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
FROM python:3.13-slim@sha256:70729b46c69b4f1e97c4822c1af3df53a1476cf5ddc6c087c0c10bc3a5678c2f AS runtime

# Fail closed: the image runs as production unless told otherwise. Production
# refuses ALLOW_PRIVATE_PROVIDER_URLS=true and requires ALLOWED_ORIGINS (https
# origins) to be set, so the container does not start without it.
# Local development (Docker Compose) sets ENVIRONMENT=development explicitly.
ENV ENVIRONMENT=production \
    PYTHONDONTWRITEBYTECODE=1 \
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
# Single worker only: the extraction limiter counts slots per process, so more
# worker processes would multiply the limit (threat model T6). Do not add workers.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port \"${PORT:-8000}\" --no-access-log --no-proxy-headers --no-server-header --log-config log_config.json"]
