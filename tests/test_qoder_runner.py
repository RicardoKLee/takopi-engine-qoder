import json
from pathlib import Path


from takopi_engine_qoder.runner import (
    ENGINE,
    QoderRunner,
    QoderStreamState,
    build_runner,
    resolve_qoder_cmd,
)
from takopi_engine_qoder.stream import translate_qoder_event
from takopi_engine_qoder import schema
from takopi.api import ActionEvent, CompletedEvent, ResumeToken, StartedEvent


def _decode_event(payload: dict) -> schema.StreamJsonMessage:
    data_payload = dict(payload)
    data_payload.setdefault("uuid", "uuid")
    data_payload.setdefault("session_id", "session")
    match data_payload.get("type"):
        case "assistant":
            message = dict(data_payload.get("message", {}))
            message.setdefault("role", "assistant")
            message.setdefault("content", [])
            message.setdefault("model", "qoder")
            data_payload["message"] = message
        case "user":
            message = dict(data_payload.get("message", {}))
            message.setdefault("role", "user")
            message.setdefault("content", [])
            data_payload["message"] = message
    return schema.decode_stream_json_line(json.dumps(data_payload).encode("utf-8"))


def test_resume_format_and_extract() -> None:
    runner = QoderRunner(qoder_cmd="qodercli")
    token = ResumeToken(engine=ENGINE, value="sid")

    assert runner.format_resume(token) == "`qodercli -r sid`"
    assert runner.extract_resume("`qodercli -r sid`") == token
    assert runner.extract_resume("qodercli --resume other") == ResumeToken(
        engine=ENGINE, value="other"
    )
    assert runner.extract_resume("`claude --resume sid`") is None


def test_build_args_non_interactive() -> None:
    runner = QoderRunner(
        qoder_cmd="qodercli",
        model="test-model",
        allowed_tools=["Read", "Write"],
        yolo=True,
        max_turns=10,
    )
    args = runner._build_args("fix bug", None)
    assert args[0:4] == ["-p", "--output-format", "stream-json", "--model"]
    assert "test-model" in args
    assert "--allowed-tools=Read,Write" in args
    assert "--yolo" in args
    assert "--max-turns" in args
    assert args[-1] == "fix bug"


def test_build_args_resume() -> None:
    runner = QoderRunner(qoder_cmd="qodercli")
    token = ResumeToken(engine=ENGINE, value="abc-123")
    args = runner._build_args("continue", token)
    assert "-r" in args
    idx = args.index("-r")
    assert args[idx + 1] == "abc-123"


def test_resolve_qoder_cmd_prefers_config() -> None:
    assert resolve_qoder_cmd({"cli_cmd": "qoderclicn"}) == "qoderclicn"


def test_translate_init_and_result() -> None:
    state = QoderStreamState()
    init = {
        "type": "system",
        "subtype": "init",
        "session_id": "sess-1",
        "model": "qoder-model",
        "cwd": "/tmp",
    }
    result = {
        "type": "result",
        "subtype": "success",
        "session_id": "sess-1",
        "duration_ms": 1,
        "duration_api_ms": 1,
        "is_error": False,
        "num_turns": 1,
        "result": "done",
    }

    started_events = translate_qoder_event(
        _decode_event(init),
        title="qoder",
        state=state,
        factory=state.factory,
    )
    assert len(started_events) == 1
    assert isinstance(started_events[0], StartedEvent)

    completed_events = translate_qoder_event(
        _decode_event(result),
        title="qoder",
        state=state,
        factory=state.factory,
    )
    assert len(completed_events) == 1
    assert isinstance(completed_events[0], CompletedEvent)
    assert completed_events[0].ok is True
    assert completed_events[0].answer == "done"


def test_translate_tool_use_and_result() -> None:
    state = QoderStreamState()

    tool_use = {
        "type": "assistant",
        "message": {
            "content": [
                {
                    "type": "tool_use",
                    "id": "tool-1",
                    "name": "Bash",
                    "input": {"command": "ls"},
                }
            ],
        },
    }
    tool_result = {
        "type": "user",
        "message": {
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "tool-1",
                    "content": "ok",
                    "is_error": False,
                }
            ],
        },
    }

    started = translate_qoder_event(
        _decode_event(tool_use),
        title="qoder",
        state=state,
        factory=state.factory,
    )
    assert len(started) == 1
    assert isinstance(started[0], ActionEvent)
    assert started[0].phase == "started"
    assert "tool-1" in state.pending_actions

    completed = translate_qoder_event(
        _decode_event(tool_result),
        title="qoder",
        state=state,
        factory=state.factory,
    )
    assert len(completed) == 1
    assert isinstance(completed[0], ActionEvent)
    assert completed[0].phase == "completed"
    assert not state.pending_actions


def test_build_runner_from_config() -> None:
    runner = build_runner(
        {
            "cli_cmd": "qodercli",
            "model": "m1",
            "allowed_tools": ["Read"],
            "yolo": True,
            "max_turns": 5,
        },
        Path("takopi.toml"),
    )
    assert runner.qoder_cmd == "qodercli"
    assert runner.model == "m1"
    assert runner.yolo is True
    assert runner.max_turns == 5
