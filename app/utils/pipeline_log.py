from __future__ import annotations

from contextvars import ContextVar
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.utils.logger import logger as app_logger


@dataclass
class LogEntry:
    step: str
    status: str
    message: str
    timestamp: str
    details: dict[str, Any] = field(default_factory=dict)


class PipelineLogger:
    def __init__(self) -> None:
        self.entries: list[LogEntry] = []

    def log(
        self,
        step: str,
        status: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> LogEntry:
        entry = LogEntry(
            step=step,
            status=status,
            message=message,
            timestamp=_now(),
            details=details or {},
        )
        self.entries.append(entry)
        app_logger.info("%s | %s | %s", step, status, message)
        return entry

    def start(
        self,
        step: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> LogEntry:
        return self.log(step, "started", message, details)

    def complete(
        self,
        step: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> LogEntry:
        return self.log(step, "completed", message, details)

    def error(
        self,
        step: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> LogEntry:
        return self.log(step, "error", message, details)

    def to_list(self) -> list[dict[str, Any]]:
        return [asdict(entry) for entry in self.entries]


_pipeline_logger: ContextVar[PipelineLogger | None] = ContextVar(
    "pipeline_logger",
    default=None,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def set_pipeline_logger(pipeline_logger: PipelineLogger):
    return _pipeline_logger.set(pipeline_logger)


def reset_pipeline_logger(token) -> None:
    try:
        _pipeline_logger.reset(token)
    except ValueError:
        # Starlette runs sync streaming generators in a thread pool; the token
        # may be created in a different context than __exit__/finally cleanup.
        _pipeline_logger.set(None)


def get_pipeline_logger() -> PipelineLogger | None:
    return _pipeline_logger.get()


def pipeline_start(
    step: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> None:
    logger = get_pipeline_logger()
    if logger:
        logger.start(step, message, details)


def pipeline_complete(
    step: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> None:
    logger = get_pipeline_logger()
    if logger:
        logger.complete(step, message, details)


def pipeline_error(
    step: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> None:
    logger = get_pipeline_logger()
    if logger:
        logger.error(step, message, details)
