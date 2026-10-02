"""The Anthropic Messages adapter (ADR-059 item 4) against a fake HTTP session: the request it
builds, how it reads a reply with text and tool calls, one retry on an overload, and errors.
(Its fit with the real API is pre-production item 40.)"""

import json
from typing import Any

import pytest

from apps.ai.adapters import anthropic
from apps.ai.adapters.base import AiProviderError
from apps.ai.adapters.chat import Message, ToolCall, ToolResult, ToolSpec


class FakeResponse:
    def __init__(self, status: int, body: Any) -> None:
        self.status_code = status
        self._body = body

    def json(self) -> Any:
        return self._body


class FakeSession:
    def __init__(self, *responses: FakeResponse) -> None:
        self.responses = list(responses)
        self.sent: list[dict[str, Any]] = []

    def post(self, url: str, *, json: Any, headers: Any, timeout: float) -> FakeResponse:
        self.sent.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        return self.responses.pop(0)


REPLY = {
    "model": "claude-sonnet-5",
    "stop_reason": "tool_use",
    "content": [
        {"type": "text", "text": "Let me check."},
        {"type": "tool_use", "id": "toolu_1", "name": "top_products", "input": {"limit": 3}},
    ],
    "usage": {"input_tokens": 812, "output_tokens": 41},
}
TOOLS = [ToolSpec("top_products", "Products by sales.", {"type": "object", "properties": {}})]


@pytest.fixture(autouse=True)
def no_wait(monkeypatch):
    monkeypatch.setattr(anthropic, "BACKOFF_SECONDS", 0)


def test_the_request_and_a_reply_with_a_tool_call():
    session = FakeSession(FakeResponse(200, REPLY))
    provider = anthropic.AnthropicChat("test-key", "claude-sonnet-5", session=session)
    messages = [
        Message("user", text="Top products?"),
        Message("assistant", text="", tool_calls=(ToolCall("toolu_0", "top_products", {}),)),
        Message("user", tool_results=(ToolResult("toolu_0", json.dumps({"rows": []})),)),
    ]
    turn = provider.chat("Be brief.", messages, TOOLS, timeout=12)
    [sent] = session.sent
    assert sent["url"] == "https://api.anthropic.com/v1/messages" and sent["timeout"] == 12
    assert sent["headers"]["x-api-key"] == "test-key"
    assert sent["headers"]["anthropic-version"] == "2023-06-01"
    body = sent["json"]
    assert (body["model"], body["system"], body["max_tokens"]) == (
        "claude-sonnet-5",
        "Be brief.",
        1024,
    )
    assert body["tools"] == [
        {
            "name": "top_products",
            "description": "Products by sales.",
            "input_schema": TOOLS[0].schema,
        }
    ]
    assert body["messages"][0] == {"role": "user", "content": "Top products?"}
    assert body["messages"][1]["content"] == [
        {"type": "tool_use", "id": "toolu_0", "name": "top_products", "input": {}}
    ]
    assert body["messages"][2]["content"] == [
        {"type": "tool_result", "tool_use_id": "toolu_0", "content": '{"rows": []}'}
    ]
    assert turn.text == "Let me check."
    assert turn.tool_calls == (ToolCall("toolu_1", "top_products", {"limit": 3}),)
    assert (turn.units_in, turn.units_out, turn.model) == (812, 41, "claude-sonnet-5")


def test_one_retry_when_overloaded_then_errors():
    session = FakeSession(FakeResponse(529, {}), FakeResponse(200, REPLY))
    provider = anthropic.AnthropicChat("k", "m", session=session)
    assert provider.chat("s", [Message("user", text="q")], TOOLS, timeout=5).tool_calls
    assert len(session.sent) == 2
    session = FakeSession(FakeResponse(529, {}), FakeResponse(529, {}))
    with pytest.raises(AiProviderError, match="HTTP 529"):
        anthropic.AnthropicChat("k", "m", session=session).chat("s", [], TOOLS, timeout=5)
    session = FakeSession(FakeResponse(401, {"error": {"type": "authentication_error"}}))
    with pytest.raises(AiProviderError, match="HTTP 401"):
        anthropic.AnthropicChat("k", "m", session=session).chat("s", [], TOOLS, timeout=5)
    assert len(session.sent) == 1  # not retried
    with pytest.raises(AiProviderError, match="ANTHROPIC_API_KEY"):
        anthropic.AnthropicChat("", "m")


def test_an_error_result_is_marked():
    content = anthropic._content(Message("user", tool_results=(ToolResult("t", "{}", error=True),)))
    assert content == [
        {"type": "tool_result", "tool_use_id": "t", "content": "{}", "is_error": True}
    ]
