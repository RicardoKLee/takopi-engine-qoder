"""Msgspec models for Qoder CLI stream-json output (Claude Code compatible)."""

from __future__ import annotations

from typing import Any, Literal

import msgspec


class StreamTextBlock(
    msgspec.Struct, tag="text", tag_field="type", forbid_unknown_fields=False
):
    text: str


class StreamThinkingBlock(
    msgspec.Struct, tag="thinking", tag_field="type", forbid_unknown_fields=False
):
    thinking: str
    signature: str


class StreamToolUseBlock(
    msgspec.Struct, tag="tool_use", tag_field="type", forbid_unknown_fields=False
):
    id: str
    name: str
    input: dict[str, Any]


class StreamToolResultBlock(
    msgspec.Struct, tag="tool_result", tag_field="type", forbid_unknown_fields=False
):
    tool_use_id: str
    content: str | list[dict[str, Any]] | None = None
    is_error: bool | None = None


type StreamContentBlock = (
    StreamTextBlock | StreamThinkingBlock | StreamToolUseBlock | StreamToolResultBlock
)


class StreamUserMessageBody(msgspec.Struct, forbid_unknown_fields=False):
    role: Literal["user"]
    content: str | list[StreamContentBlock]


class StreamAssistantMessageBody(msgspec.Struct, forbid_unknown_fields=False):
    role: Literal["assistant"]
    content: list[StreamContentBlock]
    model: str
    error: str | None = None


class StreamUserMessage(
    msgspec.Struct, tag="user", tag_field="type", forbid_unknown_fields=False
):
    message: StreamUserMessageBody
    uuid: str | None = None
    parent_tool_use_id: str | None = None
    session_id: str | None = None


class StreamAssistantMessage(
    msgspec.Struct, tag="assistant", tag_field="type", forbid_unknown_fields=False
):
    message: StreamAssistantMessageBody
    parent_tool_use_id: str | None = None
    uuid: str | None = None
    session_id: str | None = None


class StreamSystemMessage(
    msgspec.Struct, tag="system", tag_field="type", forbid_unknown_fields=False
):
    subtype: str
    session_id: str | None = None
    uuid: str | None = None
    cwd: str | None = None
    tools: list[str] | None = None
    mcp_servers: list[Any] | None = None
    model: str | None = None
    permissionMode: str | None = None
    output_style: str | None = None
    apiKeySource: str | None = None


class StreamResultMessage(
    msgspec.Struct, tag="result", tag_field="type", forbid_unknown_fields=False
):
    subtype: str
    duration_ms: int
    duration_api_ms: int
    is_error: bool
    num_turns: int
    session_id: str
    total_cost_usd: float | None = None
    usage: dict[str, Any] | None = None
    result: str | None = None
    structured_output: Any = None


class StreamEventMessage(
    msgspec.Struct, tag="stream_event", tag_field="type", forbid_unknown_fields=False
):
    uuid: str
    session_id: str
    event: dict[str, Any]
    parent_tool_use_id: str | None = None


type StreamJsonMessage = (
    StreamUserMessage
    | StreamAssistantMessage
    | StreamSystemMessage
    | StreamResultMessage
    | StreamEventMessage
)

_DECODER = msgspec.json.Decoder(StreamJsonMessage)


def decode_stream_json_line(line: str | bytes) -> StreamJsonMessage:
    return _DECODER.decode(line)
