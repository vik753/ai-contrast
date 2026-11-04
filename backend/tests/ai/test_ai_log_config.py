"""S6-T2 AC3-AC4: SDK loggers stay quiet (T1 control 3), also when the SDK log variables are set."""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap

import pytest

from tests.ai.helpers import BACKEND, KEY, LOG_CONFIG, TEXTS


@pytest.mark.parametrize("name", ["anthropic", "openai"])
def test_log_config_sets_the_sdk_loggers_to_warning(name: str) -> None:
    loggers = json.loads(LOG_CONFIG.read_text(encoding="utf-8"))["loggers"]

    assert loggers[name]["level"] == "WARNING"


PROBE = textwrap.dedent(
    """
    import asyncio, json, logging.config, sys
    sys.path.insert(0, sys.argv[1])
    # Same order as uvicorn: the logging config first, then the application import.
    logging.config.dictConfig(json.load(open(sys.argv[2])))
    import httpx2
    from pydantic import SecretStr
    from app.ai.factory import provider_for
    from app.ai.presets import PresetId
    from tests.ai.helpers import FakeUpstream, make_request

    async def go():
        for preset in (PresetId.ANTHROPIC, PresetId.OPENAI):
            key = SecretStr(sys.argv[3])
            provider = provider_for(preset, "test-model-1", key, None, transport=FakeUpstream())
            await provider.check()
            await provider.complete_json(make_request())
            fail = FakeUpstream(lambda r: httpx2.Response(500, text="SDKBODY"))
            bad = provider_for(preset, "test-model-1", key, None, transport=fail)
            try:
                await bad.check()
            except Exception:
                pass

    asyncio.run(go())
    """
)


def test_log_output_is_clean_when_the_sdk_log_variables_are_set(tmp_path: object) -> None:
    import os  # noqa: PLC0415 - the environment of the child process only

    env = {
        **os.environ,
        "ANTHROPIC_LOG": "debug",
        "OPENAI_LOG": "debug",
        "ANTHROPIC_OPEN_TELEMETRY_TRACES_CONTENT_MODE": "content",
    }
    result = subprocess.run(  # noqa: S603 - fixed arguments, test only
        [sys.executable, "-c", PROBE, str(BACKEND), str(LOG_CONFIG), KEY],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    output = result.stdout + result.stderr

    assert result.returncode == 0, output[-2000:]
    assert KEY not in output
    assert "SDKBODY" not in output
    assert not any(text in output for text in TEXTS)
    assert "Request options" not in output
    assert "json_data" not in output
