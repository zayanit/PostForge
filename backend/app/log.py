"""Structured JSON logging shared by the API and the generation worker.

Only allowlisted fields are written. The log message and exception text are never
written, because they may contain credentials, prompts, SQL, or signed URLs; record
an exception's class name in `error_type` instead.
"""

from __future__ import annotations

import json
import logging

LOG_FIELDS = (
    "event",
    "request_id",
    "provider",
    "code",
    "duration_ms",
    "provider_request_id",
    "generation_id",
    "brand_id",
    "outcome",
    "recovery",
    "error_type",
)


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "level": record.levelname,
            "logger": record.name,
        }
        for key in LOG_FIELDS:
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        # UUIDs and other identifiers serialize as strings.
        return json.dumps(payload, default=str)


def configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonLogFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)
