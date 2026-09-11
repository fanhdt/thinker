import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

from app.core.config import settings

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


class JsonFormatter(logging.Formatter):
    """Format tiap baris log sebagai satu objek JSON.

    Kenapa JSON, bukan format teks seperti sebelumnya: supaya log bisa
    di-grep/parse terstruktur (mis. filter semua event `llm_call` yang
    `duration_ms > 1000`). Tetap ditulis ke stdout, bukan ke sistem
    observability eksternal -- itu abstraksi yang belum dibutuhkan untuk
    single user MVP.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": request_id_var.get(),
        }

        event_data = getattr(record, "event_data", None)
        if event_data:
            payload["data"] = event_data
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging() -> None:
    log_level = logging.DEBUG if settings.debug else logging.INFO

    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(JsonFormatter())

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.handlers = [handler]


def log_event(logger: logging.Logger, event: str, /, **fields: Any) -> None:
    """Log satu event terstruktur, mis:

        log_event(logger, "llm_call", method="create_plan", duration_ms=842, success=True)

    `event` jadi `message` di JSON output, `fields` masuk ke key `data`.
    Helper kecil ini menghindari menulis `extra={"event_data": {...}}`
    berulang-ulang di tiap titik pemanggilan (Bagian 21: request, model call,
    token usage, retrieval, selected tools, planner decision, task execution,
    failures, latency -- semua lewat satu pola yang sama).
    """
    logger.info(event, extra={"event_data": fields})
