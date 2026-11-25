"""Structured JSON logging with PII redaction applied to every record."""

from __future__ import annotations

import json
import logging
import sys
import time

from .pii import redact


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)) + "Z",
            "level": record.levelname,
            "logger": record.name,
            "msg": redact(record.getMessage()),
        }
        extra = getattr(record, "fields", None)
        if isinstance(extra, dict):
            payload.update({k: redact(v) if isinstance(v, str) else v for k, v in extra.items()})
        if record.exc_info:
            payload["exc"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    # Third-party libraries can be chatty and may log payloads: keep them quiet.
    for noisy in ("httpx", "httpx2", "httpcore", "websockets", "mcp", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def audit(logger: logging.Logger, event: str, **fields: object) -> None:
    """Emit an audit event. Never pass raw transcripts here unless explicitly enabled."""
    logger.info(event, extra={"fields": {"event": event, **fields}})
