"""S2-T1 AC5 and AC8: global request body limit and CORS for the upload route.

``BodySizeLimitMiddleware`` (pure ASGI) rejects a body above the limit with
``413 {"error": "request_too_large"}`` on every route except ``/api/extract``
(which uses ``MAX_FILE_BYTES`` and answers ``file_too_large``). It rejects by
``Content-Length`` before the body is read, and by counting ``http.request``
chunks. It sits between CORS and the error catcher, so a 413 to an allowed
origin carries the CORS headers. Threats: T6, T4.
"""

from __future__ import annotations

import importlib
import json
from collections.abc import Callable

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from starlette.middleware.cors import CORSMiddleware

from app.middleware import ErrorCatcherMiddleware
from tests.asgi_stream import chunks, endless, post_scope, run_driven
from tests.helpers import ALLOWED_ORIGIN, OTHER_ORIGIN

ECHO = "/api/test/echo-size"
NEAR_EXTRACT = "/api/extract-other"
EXTRACT = "/api/extract"
JSON = {"Content-Type": "application/json"}
DEFAULT_MAX_JSON_BODY_BYTES = 65536
MIB = 1024 * 1024


def _add_echo_route(app: FastAPI, path: str = ECHO) -> dict[str, int]:
    """A test-only POST route that reads the whole body. Returns a counter of
    how often the handler ran."""
    calls = {"count": 0}

    async def echo(request: Request) -> dict[str, int]:
        calls["count"] += 1
        body = await request.body()
        return {"size": len(body)}

    app.add_api_route(path, echo, methods=["POST"])
    return calls


def _app_with_echo(make_app: Callable[..., FastAPI], **settings: object) -> FastAPI:
    app = make_app(**settings)
    _add_echo_route(app)
    return app


# --- Public interface and placement ---------------------------------------------------


def test_body_size_limit_middleware_importable() -> None:
    module = importlib.import_module("app.middleware.body_limit")

    assert hasattr(module, "BodySizeLimitMiddleware")


def test_body_size_limit_middleware_sits_between_cors_and_error_catcher(
    make_app: Callable[..., FastAPI],
) -> None:
    body_limit = importlib.import_module("app.middleware.body_limit").BodySizeLimitMiddleware
    # `user_middleware` lists the outermost middleware first.
    classes = [m.cls for m in make_app().user_middleware]

    assert body_limit in classes
    assert classes.index(CORSMiddleware) < classes.index(body_limit)
    assert classes.index(body_limit) < classes.index(ErrorCatcherMiddleware)


# --- JSON routes: by Content-Length ----------------------------------------------------


def test_body_above_default_json_limit_returns_413_request_too_large(
    make_app: Callable[..., FastAPI], make_client: Callable[..., TestClient]
) -> None:
    client = make_client(_app_with_echo(make_app))

    response = client.post(ECHO, content=b"a" * (DEFAULT_MAX_JSON_BODY_BYTES + 1), headers=JSON)

    assert response.status_code == 413
    assert response.json() == {"error": "request_too_large"}


def test_body_at_default_json_limit_accepted(
    make_app: Callable[..., FastAPI], make_client: Callable[..., TestClient]
) -> None:
    client = make_client(_app_with_echo(make_app))

    response = client.post(ECHO, content=b"a" * DEFAULT_MAX_JSON_BODY_BYTES, headers=JSON)

    assert response.status_code == 200
    assert response.json() == {"size": DEFAULT_MAX_JSON_BODY_BYTES}


def test_body_above_configured_json_limit_returns_413(
    make_app: Callable[..., FastAPI], make_client: Callable[..., TestClient]
) -> None:
    client = make_client(_app_with_echo(make_app, max_json_body_bytes=100))

    response = client.post(ECHO, content=b"a" * 101, headers=JSON)

    assert response.status_code == 413
    assert response.json() == {"error": "request_too_large"}


def test_json_route_content_length_above_limit_rejected_before_body_read(
    make_app: Callable[..., FastAPI],
) -> None:
    app = make_app()
    calls = _add_echo_route(app)
    scope = post_scope(
        ECHO, content_type="application/json", content_length=DEFAULT_MAX_JSON_BODY_BYTES + 1
    )

    run = run_driven(app, scope, chunks(b"a" * 1024))

    assert run.status == 413
    assert json.loads(run.body) == {"error": "request_too_large"}
    assert run.body_read_before_response() is False
    assert calls["count"] == 0


def test_json_route_file_sized_body_returns_413(
    make_app: Callable[..., FastAPI], make_client: Callable[..., TestClient]
) -> None:
    """The file limit is for /api/extract only."""
    client = make_client(_app_with_echo(make_app))

    response = client.post(ECHO, content=b"a" * MIB, headers=JSON)

    assert response.status_code == 413
    assert response.json() == {"error": "request_too_large"}


def test_path_starting_with_extract_uses_json_limit(
    make_app: Callable[..., FastAPI], make_client: Callable[..., TestClient]
) -> None:
    app = make_app()
    _add_echo_route(app, NEAR_EXTRACT)

    response = make_client(app).post(NEAR_EXTRACT, content=b"a" * (100 * 1024), headers=JSON)

    assert response.status_code == 413
    assert response.json() == {"error": "request_too_large"}


def test_unknown_route_body_above_limit_returns_413(
    make_client: Callable[..., TestClient],
) -> None:
    response = make_client().post(
        "/api/does-not-exist", content=b"a" * (DEFAULT_MAX_JSON_BODY_BYTES + 1), headers=JSON
    )

    assert response.status_code == 413
    assert response.json() == {"error": "request_too_large"}


# --- JSON routes: by counting chunks ---------------------------------------------------


def test_chunked_body_above_json_limit_returns_413(
    make_app: Callable[..., FastAPI], make_client: Callable[..., TestClient]
) -> None:
    client = make_client(_app_with_echo(make_app))
    parts = [b"a" * 8192] * 9  # 72 KiB, no Content-Length

    response = client.post(ECHO, content=iter(parts), headers=JSON)

    assert response.status_code == 413
    assert response.json() == {"error": "request_too_large"}


def test_chunked_body_below_json_limit_accepted(
    make_app: Callable[..., FastAPI], make_client: Callable[..., TestClient]
) -> None:
    client = make_client(_app_with_echo(make_app))

    response = client.post(ECHO, content=iter([b"a" * 1000, b"b" * 1000]), headers=JSON)

    assert response.status_code == 200
    assert response.json() == {"size": 2000}


def test_streamed_body_longer_than_content_length_returns_413(
    make_app: Callable[..., FastAPI],
) -> None:
    app = _app_with_echo(make_app, max_json_body_bytes=4096)
    scope = post_scope(ECHO, content_type="application/json", content_length=10)

    run = run_driven(app, scope, endless(b"a" * 1024, max_total=10 * MIB))

    assert run.status == 413
    assert json.loads(run.body) == {"error": "request_too_large"}
    assert run.body_bytes_delivered <= 4096 + 1024


def test_streamed_body_without_content_length_returns_413(
    make_app: Callable[..., FastAPI],
) -> None:
    app = _app_with_echo(make_app, max_json_body_bytes=4096)
    scope = post_scope(
        ECHO, content_type="application/json", extra_headers=[("transfer-encoding", "chunked")]
    )

    run = run_driven(app, scope, endless(b"a" * 1024, max_total=10 * MIB))

    assert run.status == 413
    assert json.loads(run.body) == {"error": "request_too_large"}


def test_extract_route_streamed_body_uses_file_limit(make_app: Callable[..., FastAPI]) -> None:
    """A JSON-sized limit must not apply to /api/extract."""
    app = make_app(max_json_body_bytes=100)
    body = b"synthetic text " * 100  # 1,500 bytes, above the JSON limit

    run = run_driven(app, post_scope(EXTRACT, content_length=len(body)), chunks(body))

    assert run.status == 200


# --- CORS ------------------------------------------------------------------------------


def test_413_on_json_route_carries_cors_headers_for_allowed_origin(
    make_app: Callable[..., FastAPI], make_client: Callable[..., TestClient]
) -> None:
    client = make_client(_app_with_echo(make_app, allowed_origins=[ALLOWED_ORIGIN]))

    response = client.post(
        ECHO,
        content=b"a" * (DEFAULT_MAX_JSON_BODY_BYTES + 1),
        headers={**JSON, "Origin": ALLOWED_ORIGIN},
    )

    assert response.status_code == 413
    assert response.headers.get("access-control-allow-origin") == ALLOWED_ORIGIN


def test_413_on_extract_carries_cors_headers_for_allowed_origin(
    make_client: Callable[..., TestClient],
) -> None:
    client = make_client(allowed_origins=[ALLOWED_ORIGIN], max_file_bytes=100)

    response = client.post(
        EXTRACT,
        content=b"a" * 101,
        headers={"Content-Type": "application/octet-stream", "Origin": ALLOWED_ORIGIN},
    )

    assert response.status_code == 413
    assert response.headers.get("access-control-allow-origin") == ALLOWED_ORIGIN


def test_streamed_413_carries_cors_headers_for_allowed_origin(
    make_app: Callable[..., FastAPI],
) -> None:
    app = _app_with_echo(make_app, allowed_origins=[ALLOWED_ORIGIN], max_json_body_bytes=4096)
    scope = post_scope(
        ECHO,
        content_type="application/json",
        content_length=10,
        extra_headers=[("origin", ALLOWED_ORIGIN)],
    )

    run = run_driven(app, scope, endless(b"a" * 1024, max_total=MIB))

    assert run.status == 413
    assert run.headers.get("access-control-allow-origin") == ALLOWED_ORIGIN


def test_413_for_other_origin_has_no_cors_headers(
    make_app: Callable[..., FastAPI], make_client: Callable[..., TestClient]
) -> None:
    client = make_client(_app_with_echo(make_app, allowed_origins=[ALLOWED_ORIGIN]))

    response = client.post(
        ECHO,
        content=b"a" * (DEFAULT_MAX_JSON_BODY_BYTES + 1),
        headers={**JSON, "Origin": OTHER_ORIGIN},
    )

    assert response.status_code == 413
    assert "access-control-allow-origin" not in response.headers


def _tokens(value: str | None) -> set[str]:
    return {part.strip().lower() for part in (value or "").split(",") if part.strip()}


def test_preflight_extract_with_content_type_from_allowed_origin_succeeds(
    make_client: Callable[..., TestClient],
) -> None:
    client = make_client(allowed_origins=[ALLOWED_ORIGIN])

    response = client.options(
        EXTRACT,
        headers={
            "Origin": ALLOWED_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == ALLOWED_ORIGIN
    assert "post" in _tokens(response.headers.get("access-control-allow-methods"))
    assert "content-type" in _tokens(response.headers.get("access-control-allow-headers"))


def test_preflight_extract_allowed_headers_stay_content_type_and_provider_key(
    make_client: Callable[..., TestClient],
) -> None:
    client = make_client(allowed_origins=[ALLOWED_ORIGIN])

    response = client.options(
        EXTRACT,
        headers={
            "Origin": ALLOWED_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    allowed = _tokens(response.headers.get("access-control-allow-headers"))
    # Starlette always adds the CORS-safelisted request headers.
    assert allowed - {"accept", "accept-language", "content-language"} == {
        "content-type",
        "x-provider-key",
    }


@pytest.mark.parametrize("header", ["x-file-name", "content-disposition"])
def test_preflight_extract_file_name_header_rejected(
    make_client: Callable[..., TestClient], header: str
) -> None:
    client = make_client(allowed_origins=[ALLOWED_ORIGIN])

    response = client.options(
        EXTRACT,
        headers={
            "Origin": ALLOWED_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": f"content-type, {header}",
        },
    )

    assert response.status_code == 400


def test_preflight_extract_from_other_origin_rejected(
    make_client: Callable[..., TestClient],
) -> None:
    client = make_client(allowed_origins=[ALLOWED_ORIGIN])

    response = client.options(
        EXTRACT,
        headers={
            "Origin": OTHER_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers
