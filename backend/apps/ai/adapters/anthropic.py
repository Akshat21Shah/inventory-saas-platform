"""The Anthropic Messages API with tool use (ADR-059 item 4).

TODO(verify): written from our understanding of the Messages API; before switching it on
(``AI_ASSISTANT_PROVIDER=anthropic``) check against the official docs (pre-production item 40):
the endpoint and ``anthropic-version`` header, the request (``system``, ``messages`` with
``tool_use`` / ``tool_result`` content blocks, ``tools`` with ``input_schema``, ``max_tokens``),
the response (``content`` blocks, ``stop_reason``, ``usage.input_tokens`` / ``output_tokens``), the
errors worth retrying (429, 5xx, overloaded) and the model name and its price.
"""

from __future__ import annotations

import time
from typing import Any

import requests

from apps.ai.adapters.base import AiProviderError
from apps.ai.adapters.chat import ChatTurn, Message, ToolCall, ToolSpec

URL = "https://api.anthropic.com/v1/messages"
VERSION = "2023-06-01"
MAX_TOKENS = 1024
RETRY_STATUSES = {429, 500, 502, 503, 504, 529}
BACKOFF_SECONDS = 1.0


def _content(message: Message) -> Any:
    if message.role == "assistant":
        blocks: list[dict[str, Any]] = (
            [{"type": "text", "text": message.text}] if message.text else []
        )
        blocks += [
            {"type": "tool_use", "id": c.id, "name": c.name, "input": c.args}
            for c in message.tool_calls
        ]
        return blocks
    if message.tool_results:
        return [
            {
                "type": "tool_result",
                "tool_use_id": r.call_id,
                "content": r.content,
                **({"is_error": True} if r.error else {}),
            }
            for r in message.tool_results
        ]
    return message.text


def request_body(
    model: str, system: str, messages: list[Message], tools: list[ToolSpec]
) -> dict[str, Any]:
    return {
        "model": model,
        "max_tokens": MAX_TOKENS,
        "system": system,
        "messages": [{"role": m.role, "content": _content(m)} for m in messages],
        "tools": [
            {"name": t.name, "description": t.description, "input_schema": t.schema} for t in tools
        ],
    }


def parse(data: dict[str, Any], model: str) -> ChatTurn:
    blocks = data.get("content") or []
    text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
    calls = tuple(
        ToolCall(id=str(b["id"]), name=str(b["name"]), args=dict(b.get("input") or {}))
        for b in blocks
        if b.get("type") == "tool_use"
    )
    usage = data.get("usage") or {}
    return ChatTurn(
        text=text,
        tool_calls=calls,
        units_in=int(usage.get("input_tokens") or 0),
        units_out=int(usage.get("output_tokens") or 0),
        model=str(data.get("model") or model),
        extra={"stop_reason": data.get("stop_reason")},
    )


class AnthropicChat:
    name = "anthropic"

    def __init__(self, api_key: str, model: str, session: Any = None) -> None:
        if not api_key:
            raise AiProviderError("ANTHROPIC_API_KEY isn't set")
        self.api_key = api_key
        self.model = model
        self.session = session or requests.Session()

    def chat(
        self,
        system: str,
        messages: list[Message],
        tools: list[ToolSpec],
        *,
        timeout: float,
    ) -> ChatTurn:
        body = request_body(self.model, system, messages, tools)
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": VERSION,
            "content-type": "application/json",
        }
        for attempt in (1, 2):  # one retry with a short backoff; the person is waiting
            try:
                response = self.session.post(URL, json=body, headers=headers, timeout=timeout)
            except requests.RequestException as exc:
                if attempt == 2:
                    raise AiProviderError(f"unreachable: {type(exc).__name__}") from exc
                time.sleep(BACKOFF_SECONDS)
                continue
            if response.status_code in RETRY_STATUSES and attempt == 1:
                time.sleep(BACKOFF_SECONDS)
                continue
            break
        if response.status_code != 200:
            raise AiProviderError(f"HTTP {response.status_code}")
        try:
            data = response.json()
        except ValueError as exc:
            raise AiProviderError("unreadable reply") from exc
        return parse(data, self.model)
