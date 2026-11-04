"""S7-T1 AC6: test hooks are arguments of create_app; no app.state fallback."""

from __future__ import annotations

import httpx2

from tests.check.helpers import Rig


class Exploding(httpx2.AsyncBaseTransport):
    def __init__(self) -> None:
        self.calls = 0

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        self.calls += 1
        raise AssertionError("an app.state hook was used")  # noqa: TRY003


def test_check_hook_argument_is_used_and_app_state_value_is_ignored() -> None:
    rig = Rig()
    bomb = Exploding()
    rig.app.state.provider_transport = bomb

    response = rig.check()

    assert response.status_code == 200
    assert bomb.calls == 0
    assert len(rig.upstream.seen) == 1
