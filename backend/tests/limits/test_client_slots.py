"""S6-T3 AC3: at most 1 extraction slot per client key (T6 control 4).

A request that holds a slot is simulated at the ASGI level: its body never
arrives until the test lets go (then the client disconnects).
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable
from typing import Any

import pytest
from fastapi import FastAPI

from tests.asgi_stream import AsgiRun, chunks, drive, drive_receive, post_scope

EXTRACT = "/api/extract"
GOOGLE = "/api/extract/google-doc"
SEGMENT = "/api/segment"
SAFETY = "/api/safety-check"
PATHS = [EXTRACT, GOOGLE, SEGMENT, SAFETY]
JSON = "application/json"
OCTET = "application/octet-stream"
IP_A = "198.51.100.1"
IP_B = "198.51.100.2"
IP_C = "198.51.100.3"
TEXT = b"Hello, contract."


def scope_for(
    path: str,
    ip: str | None,
    *,
    length: int = 16,
    extra: list[tuple[str, str]] | None = None,
) -> dict[str, Any]:
    content_type = OCTET if path == EXTRACT else JSON
    s = post_scope(path, content_type=content_type, content_length=length, extra_headers=extra)
    s["client"] = (ip, 50000) if ip is not None else None
    return s


class Held:
    """A request that took a slot (if it can) and waits for its body."""

    def __init__(self, app: FastAPI, path: str, ip: str | None, **kw: Any) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self._scope = scope_for(path, ip, **kw)
        self.task = asyncio.create_task(self._run(app))

    async def _run(self, app: FastAPI) -> AsgiRun:
        async def receive() -> dict[str, Any]:
            self.started.set()
            await self.release.wait()
            return {"type": "http.disconnect"}

        return await drive_receive(app, self._scope, receive)

    async def reading_body(self) -> bool:
        waiter = asyncio.create_task(self.started.wait())
        await asyncio.wait({waiter, self.task}, timeout=5, return_when=asyncio.FIRST_COMPLETED)
        waiter.cancel()
        return self.started.is_set()

    async def finish(self) -> AsgiRun:
        self.release.set()
        return await self.task


async def ok_extract(
    app: FastAPI, ip: str | None, extra: list[tuple[str, str]] | None = None
) -> AsgiRun:
    return await drive(app, scope_for(EXTRACT, ip, length=len(TEXT), extra=extra), chunks(TEXT))


def assert_busy(run: AsgiRun) -> None:
    assert run.status == 503
    assert run.body.replace(b" ", b"") == b'{"error":"busy"}'
    assert re.fullmatch(r"\d+", run.headers.get("retry-after", ""))


@pytest.mark.parametrize("path_a", PATHS)
@pytest.mark.parametrize("path_b", PATHS)
def test_second_request_from_same_ip_is_busy_on_every_endpoint_pair(
    make_app: Callable[..., FastAPI], path_a: str, path_b: str
) -> None:
    async def scenario() -> tuple[bool, bool, AsgiRun, AsgiRun]:
        app = make_app()
        a = Held(app, path_a, IP_A)
        a_reads = await a.reading_body()
        b = Held(app, path_b, IP_A)
        b_reads = await b.reading_body()
        run_b = await b.finish()
        run_a = await a.finish()
        return a_reads, b_reads, run_a, run_b

    a_reads, b_reads, _, run_b = asyncio.run(scenario())

    assert a_reads is True
    assert b_reads is False
    assert_busy(run_b)


def test_busy_per_client_is_answered_before_the_body_is_read(
    make_app: Callable[..., FastAPI],
) -> None:
    async def scenario() -> AsgiRun:
        app = make_app()
        a = Held(app, EXTRACT, IP_A)
        await a.reading_body()
        run = await drive(app, scope_for(EXTRACT, IP_A), chunks(b"x" * 16))
        await a.finish()
        return run

    run = asyncio.run(scenario())

    assert run.status == 503
    assert run.body_read_before_response() is False


def test_two_different_ips_both_proceed_up_to_the_pool_of_two(
    make_app: Callable[..., FastAPI],
) -> None:
    async def scenario() -> tuple[bool, bool, AsgiRun]:
        app = make_app()
        a = Held(app, EXTRACT, IP_A)
        b = Held(app, SEGMENT, IP_B)
        a_reads = await a.reading_body()
        b_reads = await b.reading_body()
        run_c = await drive(app, scope_for(EXTRACT, IP_C), chunks(b"x" * 16))
        await a.finish()
        await b.finish()
        return a_reads, b_reads, run_c

    a_reads, b_reads, run_c = asyncio.run(scenario())

    assert a_reads is True
    assert b_reads is True
    assert_busy(run_c)  # the shared pool of 2 is still the outer limit


def test_per_client_limit_is_configurable(make_app: Callable[..., FastAPI]) -> None:
    async def scenario() -> tuple[bool, bool]:
        app = make_app(max_extractions_per_client=2)
        a = Held(app, EXTRACT, IP_A)
        b = Held(app, SEGMENT, IP_A)
        a_reads = await a.reading_body()
        b_reads = await b.reading_body()
        await a.finish()
        await b.finish()
        return a_reads, b_reads

    assert asyncio.run(scenario()) == (True, True)


def test_unknown_clients_share_one_key(make_app: Callable[..., FastAPI]) -> None:
    async def scenario() -> tuple[bool, AsgiRun]:
        app = make_app()
        a = Held(app, EXTRACT, None)
        a_reads = await a.reading_body()
        run_b = await drive(app, scope_for(EXTRACT, "not-an-ip"), chunks(b"x" * 16))
        await a.finish()
        return a_reads, run_b

    a_reads, run_b = asyncio.run(scenario())

    assert a_reads is True
    assert_busy(run_b)


def test_production_same_rightmost_hop_is_one_client_despite_spoofed_leftmost(
    make_app: Callable[..., FastAPI],
) -> None:
    async def scenario() -> AsgiRun:
        app = make_app(environment="production")
        a = Held(app, EXTRACT, "10.0.0.1", extra=[("x-forwarded-for", "9.9.9.9, 198.51.100.50")])
        await a.reading_body()
        b_scope = scope_for(
            EXTRACT, "10.0.0.1", extra=[("x-forwarded-for", "8.8.8.8, 198.51.100.50")]
        )
        run_b = await drive(app, b_scope, chunks(b"x" * 16))
        await a.finish()
        return run_b

    assert_busy(asyncio.run(scenario()))


def test_production_different_rightmost_hops_are_different_clients(
    make_app: Callable[..., FastAPI],
) -> None:
    async def scenario() -> tuple[bool, bool]:
        app = make_app(environment="production")
        a = Held(app, EXTRACT, "10.0.0.1", extra=[("x-forwarded-for", "7.7.7.7, 198.51.100.50")])
        b = Held(app, EXTRACT, "10.0.0.1", extra=[("x-forwarded-for", "7.7.7.7, 198.51.100.51")])
        a_reads = await a.reading_body()
        b_reads = await b.reading_body()
        await a.finish()
        await b.finish()
        return a_reads, b_reads

    assert asyncio.run(scenario()) == (True, True)


def test_production_ipv6_addresses_in_one_slash_64_are_one_client(
    make_app: Callable[..., FastAPI],
) -> None:
    async def scenario() -> AsgiRun:
        app = make_app(environment="production")
        a = Held(app, EXTRACT, "10.0.0.1", extra=[("x-forwarded-for", "2001:db8:5:6::1")])
        await a.reading_body()
        b_scope = scope_for(EXTRACT, "10.0.0.1", extra=[("x-forwarded-for", "2001:db8:5:6::2")])
        run_b = await drive(app, b_scope, chunks(b"x" * 16))
        await a.finish()
        return run_b

    assert_busy(asyncio.run(scenario()))


def test_development_ignores_forwarded_for_and_uses_the_peer(
    make_app: Callable[..., FastAPI],
) -> None:
    async def scenario() -> AsgiRun:
        app = make_app(environment="development")
        a = Held(app, EXTRACT, IP_A, extra=[("x-forwarded-for", "1.1.1.1")])
        await a.reading_body()
        b_scope = scope_for(EXTRACT, IP_A, extra=[("x-forwarded-for", "2.2.2.2")])
        run_b = await drive(app, b_scope, chunks(b"x" * 16))
        await a.finish()
        return run_b

    assert_busy(asyncio.run(scenario()))


# Release: the slot of the client is free again after every way a request ends.


@pytest.mark.parametrize("path", PATHS)
def test_slot_released_after_client_disconnect(make_app: Callable[..., FastAPI], path: str) -> None:
    async def scenario() -> AsgiRun:
        app = make_app()
        a = Held(app, path, IP_A)
        await a.reading_body()
        await a.finish()
        return await ok_extract(app, IP_A)

    assert asyncio.run(scenario()).status == 200


def test_slot_released_after_success(make_app: Callable[..., FastAPI]) -> None:
    async def scenario() -> list[int | None]:
        app = make_app()
        return [(await ok_extract(app, IP_A)).status for _ in range(3)]

    assert asyncio.run(scenario()) == [200, 200, 200]


@pytest.mark.parametrize(
    ("path", "body"),
    [
        (SEGMENT, b"not json at all"),
        (SAFETY, b"not json at all"),
        (GOOGLE, b'{"document_id":"short"}'),
    ],
)
def test_slot_released_after_error_response(
    make_app: Callable[..., FastAPI], path: str, body: bytes
) -> None:
    async def scenario() -> tuple[list[int | None], AsgiRun]:
        app = make_app()
        errors = [
            (await drive(app, scope_for(path, IP_A, length=len(body)), chunks(body))).status
            for _ in range(3)
        ]
        return errors, await ok_extract(app, IP_A)

    errors, run = asyncio.run(scenario())

    assert 503 not in errors
    assert all(status is not None and status >= 400 for status in errors)
    assert run.status == 200


def test_slot_released_after_body_timeout(make_app: Callable[..., FastAPI]) -> None:
    async def scenario() -> tuple[AsgiRun, AsgiRun]:
        app = make_app(extract_body_timeout_seconds=1)

        async def stall() -> dict[str, Any]:
            await asyncio.sleep(3600)
            return {"type": "http.disconnect"}

        timed_out = await drive_receive(app, scope_for(EXTRACT, IP_A), stall)
        return timed_out, await ok_extract(app, IP_A)

    timed_out, after = asyncio.run(scenario())

    assert timed_out.status == 408
    assert after.status == 200


def test_busy_attempt_does_not_release_the_slot_of_the_holder(
    make_app: Callable[..., FastAPI],
) -> None:
    async def scenario() -> tuple[AsgiRun, AsgiRun]:
        app = make_app()
        a = Held(app, EXTRACT, IP_A)
        await a.reading_body()
        first = await drive(app, scope_for(EXTRACT, IP_A), chunks(b"x" * 16))
        second = await drive(app, scope_for(EXTRACT, IP_A), chunks(b"x" * 16))
        await a.finish()
        return first, second

    first, second = asyncio.run(scenario())

    assert_busy(first)
    assert_busy(second)


def test_refused_attempt_does_not_leak_a_shared_pool_slot(
    make_app: Callable[..., FastAPI],
) -> None:
    async def scenario() -> tuple[bool, bool]:
        app = make_app()
        a = Held(app, EXTRACT, IP_A)
        await a.reading_body()
        for _ in range(5):
            await drive(app, scope_for(EXTRACT, IP_A), chunks(b"x" * 16))
        b = Held(app, EXTRACT, IP_B)  # the second pool slot must still be free
        b_reads = await b.reading_body()
        await a.finish()
        await b.finish()
        return True, b_reads

    assert asyncio.run(scenario()) == (True, True)
