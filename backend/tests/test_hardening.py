"""backend-dev unit tests for hardening beyond the acceptance-criteria tests."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Annotated

import pytest
from fastapi import Depends, FastAPI, Header, Request
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field, ValidationError
from starlette.types import Message

from app.api.validation_errors import declared_names, sanitize_location
from app.exc_names import exception_type_names
from app.logging_filters import ExcInfoScrubber
from app.middleware._safe import MAX_LOGGED_PATH_LENGTH, log_path
from app.settings import Settings
from tests.helpers import access_lines, ai_contrast_records, http_scope, new_canary

FFFD = "\ufffd"
UPLOAD_PATH = "/api/test/upload"

# --------------------------------------------------------------------------
# Log line sanitizing
# --------------------------------------------------------------------------


def test_log_path_replaces_control_characters_with_fffd() -> None:
    logged = log_path({"path": "/api/a\nFAKE 200\r\x1b[31m\x85"})

    assert logged == f"/api/a{FFFD}FAKE 200{FFFD}{FFFD}[31m{FFFD}"


def test_log_path_truncates_long_paths() -> None:
    logged = log_path({"path": "/" + "a" * 1000})

    assert len(logged) == MAX_LOGGED_PATH_LENGTH + len("...")


def test_access_log_encoded_newline_in_path_stays_one_line(
    make_client: Callable[..., TestClient], log_capture: pytest.LogCaptureFixture
) -> None:
    client = make_client()
    log_capture.clear()

    client.get("/api/x%0Aforged%20line")

    (record,) = ai_contrast_records(log_capture)
    assert "\n" not in record.getMessage()


# --------------------------------------------------------------------------
# Exception type names
# --------------------------------------------------------------------------


def test_exception_type_names_nested_group() -> None:
    group = ExceptionGroup("outer", [ExceptionGroup("inner", [ValueError("x")]), KeyError("y")])

    assert exception_type_names(group) == "ExceptionGroup(ExceptionGroup(ValueError),KeyError)"


def test_exception_type_names_deep_group_is_bounded() -> None:
    exc: Exception = ValueError("leaf")
    for _ in range(50):
        exc = ExceptionGroup("g", [exc])

    assert exception_type_names(exc).count("ExceptionGroup") <= 9


def test_exc_info_scrubber_keeps_args_formatting_and_appends_type() -> None:
    canary = new_canary()
    try:
        raise RuntimeError(canary)  # noqa: TRY301 - building a real exc_info
    except RuntimeError as exc:
        record = logging.LogRecord(
            "x", logging.ERROR, __file__, 1, "failed %s", ("op",), (type(exc), exc, None)
        )

    scrubbed = ExcInfoScrubber().filter(record)

    assert scrubbed.getMessage() == "failed op exc_type=RuntimeError"


def test_exc_info_scrubber_unprintable_msg_falls_back() -> None:
    class _BadStr:
        def __str__(self) -> str:
            raise ValueError(new_canary())

    record = logging.LogRecord("x", logging.ERROR, __file__, 1, _BadStr(), None, None)

    scrubbed = ExcInfoScrubber().filter(record)

    assert scrubbed.getMessage() == "<unprintable log message> log_format_error=1"


# --------------------------------------------------------------------------
# 422 locations: helpers (S1-T1c AC1)
# --------------------------------------------------------------------------


def test_sanitize_location_bool_part_is_not_an_index() -> None:
    assert sanitize_location(["body", True], "int_parsing", set()) == ["body", "*"]


def test_sanitize_location_unknown_first_part_replaced() -> None:
    assert sanitize_location(["secret", "x"], "missing", {"x"}) == ["*", "x"]


class _Leaf(BaseModel):
    leaf_value: int = Field(alias="leafAlias")


class _Root(BaseModel):
    leaves: dict[str, list[_Leaf]]


async def _dep(x_extra: Annotated[str, Header()]) -> str:
    return x_extra


def test_declared_names_include_nested_aliases_and_dependencies(
    make_app: Callable[..., FastAPI],
) -> None:
    async def _endpoint(body: _Root, extra: Annotated[str, Depends(_dep)]) -> None:
        return None

    app = make_app()
    app.add_api_route("/api/test/names", _endpoint, methods=["POST"])
    route = next(r for r in app.routes if isinstance(r, APIRoute) and r.path == "/api/test/names")

    names = declared_names(route)

    assert {"body", "leaves", "leaf_value", "leafAlias", "x-extra"} <= names


# --------------------------------------------------------------------------
# Client disconnect while the body is read (tech lead decision, S1-T1b AC8)
# --------------------------------------------------------------------------


def _upload_app(make_app: Callable[..., FastAPI]) -> FastAPI:
    app = make_app()

    async def _upload(request: Request) -> dict[str, int]:
        return {"size": len(await request.body())}

    app.add_api_route(UPLOAD_PATH, _upload, methods=["POST"])
    return app


def _run_disconnecting(app: FastAPI) -> list[Message]:
    sent: list[Message] = []
    incoming: list[Message] = [
        {"type": "http.request", "body": b"partial", "more_body": True},
        {"type": "http.disconnect"},
    ]

    async def receive() -> Message:
        return incoming.pop(0)

    async def send(message: Message) -> None:
        sent.append(message)

    asyncio.run(app(http_scope("POST", UPLOAD_PATH), receive, send))
    return sent


def test_client_disconnect_sends_no_response(make_app: Callable[..., FastAPI]) -> None:
    assert _run_disconnecting(_upload_app(make_app)) == []


def test_client_disconnect_is_not_logged_as_unhandled_exception(
    make_app: Callable[..., FastAPI], log_capture: pytest.LogCaptureFixture
) -> None:
    app = _upload_app(make_app)
    log_capture.clear()

    _run_disconnecting(app)

    messages = [r.getMessage() for r in ai_contrast_records(log_capture)]
    assert not any("unhandled_exception" in m for m in messages), messages


def test_client_disconnect_access_line_status_dash_and_disconnected(
    make_app: Callable[..., FastAPI], log_capture: pytest.LogCaptureFixture
) -> None:
    app = _upload_app(make_app)
    log_capture.clear()

    _run_disconnecting(app)

    (line,) = access_lines(log_capture, "POST", UPLOAD_PATH)
    assert line.split()[2] == "-"
    assert line.endswith(" disconnected=1")
    assert "aborted" not in line


# --------------------------------------------------------------------------
# Origin edge cases (tech lead decisions, S1-T1b AC6)
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "origin",
    ["https://a.example/", "https://a.example/x", "https://a.example:8443/"],
    ids=["trailing-slash", "path", "port-and-slash"],
)
def test_settings_origin_with_any_path_rejected(origin: str) -> None:
    with pytest.raises(ValidationError):
        Settings(allowed_origins=[origin])


def test_settings_origin_scheme_and_host_lowercased() -> None:
    settings = Settings(allowed_origins=["HTTPS://App.Example:8443"])

    assert settings.allowed_origins == ["https://app.example:8443"]


@pytest.mark.parametrize(
    ("origin", "expected"),
    [("https://a.example:443", "https://a.example"), ("http://a.example:80", "http://a.example")],
)
def test_settings_origin_default_port_dropped(origin: str, expected: str) -> None:
    assert Settings(allowed_origins=[origin]).allowed_origins == [expected]


@pytest.mark.parametrize(
    "char", ["\x00", "\t", "\x1b", "\x7f", "\x80", "\x85", "\x9f"], ids=lambda c: f"0x{ord(c):02x}"
)
def test_settings_origin_with_control_character_rejected(char: str) -> None:
    with pytest.raises(ValidationError):
        Settings(allowed_origins=[f"https://a.example{char}"])


@pytest.mark.parametrize("port", ["0", "65536", "99999"])
def test_settings_origin_port_out_of_range_rejected(port: str) -> None:
    with pytest.raises(ValidationError):
        Settings(allowed_origins=[f"https://a.example:{port}"])


def test_settings_origin_non_ascii_host_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(allowed_origins=["https://пример.example"])


def test_settings_origin_ipv6_accepted() -> None:
    assert Settings(allowed_origins=["http://[::1]:5173"]).allowed_origins == ["http://[::1]:5173"]


def test_settings_wildcard_origin_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(allowed_origins=["*"])


def test_settings_env_empty_origin_entries_dropped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://a.example,, ,")

    assert Settings().allowed_origins == ["https://a.example"]


@pytest.mark.parametrize("value", ["", "   ", " , ,"], ids=["empty", "spaces", "commas"])
def test_settings_env_production_empty_allowed_origins_rejected(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("ALLOWED_ORIGINS", value)

    with pytest.raises(ValidationError):
        Settings()


def test_settings_env_development_empty_allowed_origins_disables_cors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ALLOWED_ORIGINS", "")

    assert Settings().allowed_origins == []


def test_settings_private_provider_urls_rejected_in_production() -> None:
    with pytest.raises(ValidationError):
        Settings(
            environment="production",
            allowed_origins=["https://a.example"],
            allow_private_provider_urls=True,
        )
