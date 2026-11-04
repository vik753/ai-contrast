"""S6-T2 review notes (LOW): clean error chains, odd SDK answers, text bound to its document."""

from __future__ import annotations

import httpx2
import pytest

from app.ai.port import AIError, AIRequest
from app.ai.presets import PresetId
from app.pseudo import gate
from app.pseudo.gate import PseudonymizedText, document_digest
from tests.ai.helpers import (
    KEY,
    FakeUpstream,
    Verdict,
    error_reply,
    failure,
    first_template,
    make_document,
    make_provider,
    raising,
)

PRESETS = [PresetId.ANTHROPIC, PresetId.OPENAI]
OPS = ["check", "complete_json"]


def _text(document: gate.PseudonymizedDocument, source: str | None = None) -> PseudonymizedText:
    # The only maker of a gate text is the gate module; a test uses its sentinel.
    return PseudonymizedText("some text", source or document_digest(document), gate._SENTINEL)


@pytest.mark.parametrize("op", OPS)
@pytest.mark.parametrize("preset", PRESETS)
@pytest.mark.parametrize(
    "reply",
    [error_reply(401), error_reply(500), raising(httpx2.ConnectError("x")), raising(ValueError())],
    ids=["401", "500", "connect", "value"],
)
def test_mapped_error_has_no_cause_and_no_context(preset: PresetId, op: str, reply: object) -> None:
    provider, _ = make_provider(preset, upstream=FakeUpstream(reply))  # type: ignore[arg-type]

    error = failure(provider, op)

    assert error.__cause__ is None
    assert error.__context__ is None
    assert KEY not in repr(error.__traceback__.tb_frame.f_locals if error.__traceback__ else "")


@pytest.mark.parametrize("text", ["not json", "[1]"])
@pytest.mark.parametrize("preset", PRESETS)
def test_bad_model_text_error_has_no_context(preset: PresetId, text: str) -> None:
    from tests.ai.helpers import model_reply  # noqa: PLC0415

    provider, _ = make_provider(preset, upstream=FakeUpstream(model_reply(text)))

    error = failure(provider, "complete_json")

    assert error.__context__ is None
    assert error.__cause__ is None


@pytest.mark.parametrize("block", [{"type": "text"}, {"type": "text", "text": 5}, {"type": "x"}])
@pytest.mark.parametrize("op", OPS)
def test_anthropic_text_block_without_text_is_an_ai_error(
    op: str, block: dict[str, object]
) -> None:
    def reply(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            json={
                "id": "m",
                "type": "message",
                "role": "assistant",
                "model": "x",
                "content": [block],
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        )

    provider, _ = make_provider(PresetId.ANTHROPIC, upstream=FakeUpstream(reply))

    error = failure(provider, "complete_json")

    assert isinstance(error, AIError)
    assert error.code == "provider_bad_response"


@pytest.mark.parametrize("reply_json", [{"choices": [{}]}, {"choices": ["x"]}, {}])
def test_check_runs_the_shape_test_openai(reply_json: dict[str, object]) -> None:
    provider, _ = make_provider(
        PresetId.OPENAI, upstream=FakeUpstream(lambda r: httpx2.Response(200, json=reply_json))
    )

    assert failure(provider, "check").code == "provider_bad_response"


def test_check_accepts_an_empty_answer() -> None:
    from tests.ai.helpers import model_reply, run  # noqa: PLC0415

    for preset in PRESETS:
        provider, _ = make_provider(preset, upstream=FakeUpstream(model_reply("")))
        assert run(provider, "check")


def test_request_with_a_text_of_the_same_document_is_accepted() -> None:
    document = make_document()

    request = AIRequest(
        template=first_template(),
        document=document,
        schema=Verdict,
        max_tokens=64,
        text=_text(document),
    )

    assert request.text is not None


def test_request_with_a_text_of_another_document_is_refused() -> None:
    document = make_document()
    other = make_document("1. Some other clause.")

    with pytest.raises(ValueError, match=r"."):
        AIRequest(
            template=first_template(),
            document=document,
            schema=Verdict,
            max_tokens=64,
            text=_text(other),
        )


def test_request_with_a_text_with_a_made_up_source_is_refused() -> None:
    document = make_document()

    with pytest.raises(ValueError, match=r"."):
        AIRequest(
            template=first_template(),
            document=document,
            schema=Verdict,
            max_tokens=64,
            text=_text(document, "0" * 64),
        )


def test_document_digest_differs_for_different_documents_and_is_stable() -> None:
    first, second = make_document(), make_document("1. Other.")

    assert document_digest(first) == document_digest(make_document())
    assert document_digest(first) != document_digest(second)
