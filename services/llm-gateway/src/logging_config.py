"""Structured JSON log formatter.

Outputs one JSON object per log line with consistent fields:
  {"ts": "...", "level": "...", "logger": "...", "msg": "...", ...}

Extra keys passed via `logger.info("msg", extra={"key": "val"})` are
merged into the top-level object for easy filtering in log aggregation
tools (Loki, CloudWatch, Datadog, etc.).
"""

import json
import logging
import traceback
from datetime import datetime, timezone


class JSONFormatter(logging.Formatter):
    """Formats log records as single-line JSON objects."""

    # Internal LogRecord attributes to exclude from extra fields.
    # Computed once at class load, not per format() call.
    _SKIP = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__)

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }

        # Merge extra fields (skip internal LogRecord attributes)
        for key, val in record.__dict__.items():
            if key not in self._SKIP and key not in entry:
                entry[key] = val

        if record.exc_info and record.exc_info[1]:
            entry["exception"] = traceback.format_exception(*record.exc_info)

        return json.dumps(entry, default=str)
