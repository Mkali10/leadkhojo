"""Structured logging.

Rules:
  * event-named messages (noun.verb_past), never f-strings
  * never log crawled page content — a page may contain someone else's secret,
    and logging it copies that secret into our logs
  * print() is banned outside scripts/ and the CLI
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

_RESERVED = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "module",
        "msecs",
        "message",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "thread",
        "threadName",
        "taskName",
    }
)

# Never let these reach a log sink, whatever the caller passes.
_REDACT_KEYS = frozenset({"html", "body", "content", "api_key", "password", "token", "secret"})


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "event": record.getMessage(),
            "logger": record.name,
        }
        for key, value in record.__dict__.items():
            if key in _RESERVED or key.startswith("_"):
                continue
            payload[key] = "[redacted]" if key.lower() in _REDACT_KEYS else value

        if record.exc_info:
            payload["error"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str)


class PlainFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        extras = {
            k: ("[redacted]" if k.lower() in _REDACT_KEYS else v)
            for k, v in record.__dict__.items()
            if k not in _RESERVED and not k.startswith("_")
        }
        suffix = f"  {extras}" if extras else ""
        return f"{record.levelname:<8} {record.getMessage()}{suffix}"


def configure_logging(*, level: str = "INFO", json_output: bool = True) -> None:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter() if json_output else PlainFormatter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())

    # These are chatty and tell us nothing we do not already record.
    for noisy in ("httpx", "httpcore", "asyncio", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


__all__ = ["configure_logging"]
