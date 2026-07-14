from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from takopi.api import (
    Action,
    ActionEvent,
    CompletedEvent,
    EventFactory,
    ResumeToken,
    StartedEvent,
)

from . import schema
from .tool_actions import tool_input_path, tool_kind_and_title

type StreamEvent = StartedEvent | ActionEvent | CompletedEvent

ENGINE = "qoder"


@dataclass(slots=True)
class QoderStreamState:
    factory: EventFactory = field(default_factory=lambda: EventFactory(ENGINE))
    pending_actions: dict[str, Action] = field(default_factory=dict)
    last_assistant_text: str | None = None
    note_seq: int = 0


def _normalize_tool_result(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str) and text:
                    parts.append(text)
            elif isinstance(item, str):
                parts.append(item)
        return "\n".join(part for part in parts if part)
    if isinstance(content, dict):
        text = content.get("text")
        if isinstance(text, str):
            return text
    return str(content)


def _tool_action(
    content: schema.StreamToolUseBlock,
    *,
    parent_tool_use_id: str | None,
) -> Action:
    tool_id = content.id
    tool_name = str(content.name or "tool")
    tool_input = content.input

    kind, title = tool_kind_and_title(
        tool_name, tool_input, path_keys=("file_path", "path")
    )

    detail: dict[str, Any] = {"name": tool_name, "input": tool_input}
    if parent_tool_use_id:
        detail["parent_tool_use_id"] = parent_tool_use_id

    if kind == "file_change":
        path = tool_input_path(tool_input, path_keys=("file_path", "path"))
        if path:
            detail["changes"] = [{"path": path, "kind": "update"}]

    return Action(id=tool_id, kind=kind, title=title, detail=detail)


def _tool_result_event(
    content: schema.StreamToolResultBlock,
    *,
    action: Action,
    factory: EventFactory,
) -> StreamEvent:
    is_error = content.is_error is True
    normalized = _normalize_tool_result(content.content)
    detail = action.detail | {
        "tool_use_id": content.tool_use_id,
        "result_preview": normalized,
        "result_len": len(normalized),
        "is_error": is_error,
    }
    return factory.action_completed(
        action_id=action.id,
        kind=action.kind,
        title=action.title,
        ok=not is_error,
        detail=detail,
    )


def _extract_error(event: schema.StreamResultMessage) -> str | None:
    if event.is_error:
        if isinstance(event.result, str) and event.result:
            return event.result
        subtype = event.subtype
        if subtype:
            return f"qoder run failed ({subtype})"
        return "qoder run failed"
    return None


def _usage_payload(event: schema.StreamResultMessage) -> dict[str, Any]:
    usage: dict[str, Any] = {}
    for key in ("total_cost_usd", "duration_ms", "duration_api_ms", "num_turns"):
        value = getattr(event, key, None)
        if value is not None:
            usage[key] = value
    if event.usage is not None:
        usage["usage"] = event.usage
    return usage


def translate_qoder_event(
    event: schema.StreamJsonMessage,
    *,
    title: str,
    state: QoderStreamState,
    factory: EventFactory,
) -> list[StreamEvent]:
    match event:
        case schema.StreamSystemMessage(subtype=subtype):
            if subtype != "init":
                return []
            session_id = event.session_id
            if not session_id:
                return []
            meta: dict[str, Any] = {}
            for key in (
                "cwd",
                "tools",
                "permissionMode",
                "output_style",
                "apiKeySource",
                "mcp_servers",
            ):
                value = getattr(event, key, None)
                if value is not None:
                    meta[key] = value
            model = event.model
            token = ResumeToken(engine=ENGINE, value=session_id)
            event_title = str(model) if isinstance(model, str) and model else title
            return [factory.started(token, title=event_title, meta=meta or None)]

        case schema.StreamAssistantMessage(
            message=message, parent_tool_use_id=parent_tool_use_id
        ):
            out: list[StreamEvent] = []
            for content in message.content:
                match content:
                    case schema.StreamToolUseBlock():
                        action = _tool_action(
                            content, parent_tool_use_id=parent_tool_use_id
                        )
                        state.pending_actions[action.id] = action
                        out.append(
                            factory.action_started(
                                action_id=action.id,
                                kind=action.kind,
                                title=action.title,
                                detail=action.detail,
                            )
                        )
                    case schema.StreamThinkingBlock(thinking=thinking):
                        if not thinking:
                            continue
                        state.note_seq += 1
                        action_id = f"qoder.thinking.{state.note_seq}"
                        detail: dict[str, Any] = {}
                        if parent_tool_use_id:
                            detail["parent_tool_use_id"] = parent_tool_use_id
                        out.append(
                            factory.action_completed(
                                action_id=action_id,
                                kind="note",
                                title=thinking,
                                ok=True,
                                detail=detail or None,
                            )
                        )
                    case schema.StreamTextBlock(text=text):
                        if text:
                            state.last_assistant_text = text
                    case _:
                        continue
            return out

        case schema.StreamUserMessage(message=message):
            if not isinstance(message.content, list):
                return []
            out: list[StreamEvent] = []
            for content in message.content:
                if not isinstance(content, schema.StreamToolResultBlock):
                    continue
                tool_use_id = content.tool_use_id
                action = state.pending_actions.pop(tool_use_id, None)
                if action is None:
                    action = Action(
                        id=tool_use_id,
                        kind="tool",
                        title="tool result",
                        detail={},
                    )
                out.append(_tool_result_event(content, action=action, factory=factory))
            return out

        case schema.StreamResultMessage():
            ok = not event.is_error
            result_text = event.result or ""
            if ok and not result_text and state.last_assistant_text:
                result_text = state.last_assistant_text

            resume = ResumeToken(engine=ENGINE, value=event.session_id)
            error = None if ok else _extract_error(event)
            usage = _usage_payload(event)

            return [
                factory.completed(
                    ok=ok,
                    answer=result_text,
                    resume=resume,
                    error=error,
                    usage=usage or None,
                )
            ]

        case _:
            return []
