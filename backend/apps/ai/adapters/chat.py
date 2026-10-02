"""The chat-with-tools interface (ADR-059 item 4): a provider-neutral conversation of the
person's question, the model's tool calls and the tools' results."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class ToolSpec:
    """A tool as the model sees it: a name, what it is for and a JSON schema of its arguments."""

    name: str
    description: str
    schema: dict[str, Any]


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    args: dict[str, Any]


@dataclass(frozen=True)
class ToolResult:
    call_id: str
    content: str  # JSON text
    error: bool = False


@dataclass(frozen=True)
class Message:
    """``user`` with the question (``text``) or with tool results; ``assistant`` with its text
    and the tools it asked for."""

    role: str
    text: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    tool_results: tuple[ToolResult, ...] = ()


@dataclass(frozen=True)
class ChatTurn:
    """The model's reply: text, and tool calls when it wants figures first."""

    text: str
    tool_calls: tuple[ToolCall, ...] = ()
    units_in: int = 0
    units_out: int = 0
    model: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


class ChatProvider(Protocol):
    name: str

    def chat(
        self,
        system: str,
        messages: list[Message],
        tools: list[ToolSpec],
        *,
        timeout: float,
    ) -> ChatTurn: ...
