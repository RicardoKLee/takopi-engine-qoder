from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import msgspec

from takopi.api import (
    ActionEvent,
    CompletedEvent,
    EngineId,
    JsonlSubprocessRunner,
    ResumeToken,
    StartedEvent,
    get_logger,
)

from . import schema
from .stream import QoderStreamState, translate_qoder_event

type StreamEvent = StartedEvent | ActionEvent | CompletedEvent

logger = get_logger(__name__)

ENGINE: EngineId = "qoder"
DEFAULT_ALLOWED_TOOLS = ["Bash", "Read", "Edit", "Write"]

_RESUME_RE = re.compile(
    r"(?im)^\s*`?(?:qodercli|qoderclicn)\s+(?:-(?:r|resume)|--resume)\s+(?P<token>[^`\s]+)`?\s*$"
)


def _coerce_comma_list(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (list, tuple, set)):
        parts = [str(item) for item in value if item is not None]
        joined = ",".join(part for part in parts if part)
        return joined or None
    text = str(value)
    return text or None


def _resolve_run_options_model() -> str | None:
    try:
        from takopi.runners.run_options import get_run_options
    except ImportError:
        return None
    run_options = get_run_options()
    if run_options is None:
        return None
    return run_options.model


@dataclass(slots=True)
class QoderRunner(JsonlSubprocessRunner):
    engine: EngineId = ENGINE
    resume_re: re.Pattern[str] = _RESUME_RE

    qoder_cmd: str = "qodercli"
    model: str | None = None
    allowed_tools: list[str] | None = None
    yolo: bool = False
    max_turns: int | None = None
    session_title: str = "qoder"
    logger = logger

    def format_resume(self, token: ResumeToken) -> str:
        if token.engine != ENGINE:
            raise RuntimeError(f"resume token is for engine {token.engine!r}")
        return f"`{self.qoder_cmd} -r {token.value}`"

    def is_resume_line(self, line: str) -> bool:
        return bool(self.resume_re.match(line))

    def extract_resume(self, text: str | None) -> ResumeToken | None:
        if not text:
            return None
        found: str | None = None
        for match in self.resume_re.finditer(text):
            token = match.group("token")
            if token:
                found = token
        if not found:
            return None
        return ResumeToken(engine=ENGINE, value=found)

    def _build_args(self, prompt: str, resume: ResumeToken | None) -> list[str]:
        args: list[str] = ["-p", "--output-format", "stream-json"]
        if resume is not None:
            args.extend(["-r", resume.value])

        model = self.model
        override = _resolve_run_options_model()
        if override:
            model = override
        if model is not None:
            args.extend(["--model", str(model)])

        allowed_tools = _coerce_comma_list(self.allowed_tools)
        if allowed_tools is not None:
            args.append(f"--allowed-tools={allowed_tools}")

        if self.yolo is True:
            args.append("--yolo")

        if self.max_turns is not None:
            args.extend(["--max-turns", str(self.max_turns)])

        args.append(prompt)
        return args

    def command(self) -> str:
        return self.qoder_cmd

    def build_args(
        self,
        prompt: str,
        resume: ResumeToken | None,
        *,
        state: Any,
    ) -> list[str]:
        return self._build_args(prompt, resume)

    def stdin_payload(
        self,
        prompt: str,
        resume: ResumeToken | None,
        *,
        state: Any,
    ) -> bytes | None:
        return None

    def new_state(self, prompt: str, resume: ResumeToken | None) -> QoderStreamState:
        return QoderStreamState()

    def start_run(
        self,
        prompt: str,
        resume: ResumeToken | None,
        *,
        state: QoderStreamState,
    ) -> None:
        return None

    def decode_jsonl(self, *, line: bytes) -> schema.StreamJsonMessage:
        return schema.decode_stream_json_line(line)

    def decode_error_events(
        self,
        *,
        raw: str,
        line: str,
        error: Exception,
        state: QoderStreamState,
    ) -> list[StreamEvent]:
        if isinstance(error, msgspec.DecodeError):
            self.get_logger().warning(
                "jsonl.msgspec.invalid",
                tag=self.tag(),
                error=str(error),
                error_type=error.__class__.__name__,
            )
            return []
        return super().decode_error_events(raw=raw, line=line, error=error, state=state)

    def invalid_json_events(
        self,
        *,
        raw: str,
        line: str,
        state: QoderStreamState,
    ) -> list[StreamEvent]:
        return []

    def translate(
        self,
        data: schema.StreamJsonMessage,
        *,
        state: QoderStreamState,
        resume: ResumeToken | None,
        found_session: ResumeToken | None,
    ) -> list[StreamEvent]:
        return translate_qoder_event(
            data,
            title=self.session_title,
            state=state,
            factory=state.factory,
        )

    def process_error_events(
        self,
        rc: int,
        *,
        resume: ResumeToken | None,
        found_session: ResumeToken | None,
        state: QoderStreamState,
    ) -> list[StreamEvent]:
        message = f"qoder failed (rc={rc})."
        resume_for_completed = found_session or resume
        return [
            self.note_event(message, state=state, ok=False),
            state.factory.completed_error(error=message, resume=resume_for_completed),
        ]

    def stream_end_events(
        self,
        *,
        resume: ResumeToken | None,
        found_session: ResumeToken | None,
        state: QoderStreamState,
    ) -> list[StreamEvent]:
        if not found_session:
            message = "qoder finished but no session_id was captured"
            return [
                state.factory.completed_error(
                    error=message,
                    resume=resume,
                )
            ]

        message = "qoder finished without a result event"
        return [
            state.factory.completed_error(
                error=message,
                answer=state.last_assistant_text or "",
                resume=found_session,
            )
        ]


def resolve_qoder_cmd(config: dict[str, Any]) -> str:
    configured = config.get("cli_cmd")
    if isinstance(configured, str) and configured.strip():
        return configured.strip()

    for candidate in ("qodercli", "qoderclicn"):
        found = shutil.which(candidate)
        if found:
            return candidate

    return "qodercli"


def build_runner(config: dict[str, Any], _config_path: Path) -> QoderRunner:
    qoder_cmd = resolve_qoder_cmd(config)

    model = config.get("model")
    if "allowed_tools" in config:
        allowed_tools = config.get("allowed_tools")
    else:
        allowed_tools = DEFAULT_ALLOWED_TOOLS

    yolo = config.get("yolo") is True
    max_turns = config.get("max_turns")
    if max_turns is not None:
        max_turns = int(max_turns)

    title = str(model) if model is not None else "qoder"

    return QoderRunner(
        qoder_cmd=qoder_cmd,
        model=model if isinstance(model, str) else None,
        allowed_tools=allowed_tools if isinstance(allowed_tools, list) else None,
        yolo=yolo,
        max_turns=max_turns,
        session_title=title,
    )
