from __future__ import annotations

from takopi.api import EngineBackend

from .runner import build_runner

BACKEND = EngineBackend(
    id="qoder",
    build_runner=build_runner,
    cli_cmd="qodercli",
    install_cmd="https://docs.qoder.com/en/cli/using-cli",
)

__all__ = ["BACKEND", "build_runner"]
