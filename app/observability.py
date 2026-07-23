from __future__ import annotations

import json
import logging
import sys
import time
import traceback
import uuid
from datetime import datetime, timezone
from typing import TextIO

from starlette.datastructures import MutableHeaders
from starlette.types import Message, Receive, Scope, Send

from app.config import Settings


_LOG_FIELDS = (
    "event",
    "request_id",
    "method",
    "route",
    "status_code",
    "duration_ms",
    "exception_type",
    "exception_stack",
)
_QUIET_PATHS = frozenset({"/health", "/health/db"})


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in _LOG_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        return json.dumps(payload, ensure_ascii=True, separators=(",", ":"))


class ReadableLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        rendered = super().format(record)
        details = [
            f"{field}={getattr(record, field)}"
            for field in _LOG_FIELDS
            if getattr(record, field, None) is not None
        ]
        return f"{rendered} {' '.join(details)}".rstrip()


def create_application_logger(
    app_settings: Settings,
    *,
    name: str,
    stream: TextIO | None = None,
) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.handlers.clear()
    logger.setLevel(logging.INFO)
    logger.propagate = False

    handler = logging.StreamHandler(stream or sys.stderr)
    if app_settings.is_production:
        handler.setFormatter(JsonLogFormatter())
    else:
        handler.setFormatter(
            ReadableLogFormatter("%(asctime)s %(levelname)s %(message)s")
        )
    logger.addHandler(handler)
    return logger


def disable_duplicate_uvicorn_access_log() -> None:
    logging.getLogger("uvicorn.access").disabled = True


def safe_exception_details(exc: Exception) -> dict[str, object]:
    stack = [
        f"{frame.filename}:{frame.lineno} in {frame.name}"
        for frame in traceback.extract_tb(exc.__traceback__)[-20:]
    ]
    return {
        "exception_type": type(exc).__name__,
        "exception_stack": stack,
    }


class RequestLoggingMiddleware:
    def __init__(self, app, *, logger: logging.Logger) -> None:
        self.app = app
        self.logger = logger

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = uuid.uuid4().hex
        state = scope.setdefault("state", {})
        if isinstance(state, dict):
            state["request_id"] = request_id

        status_code = 500
        started_at = time.perf_counter()

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                MutableHeaders(scope=message)["x-request-id"] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        except Exception as exc:
            if scope["path"] not in _QUIET_PATHS:
                self.logger.error(
                    "request_failed",
                    extra={
                        "event": "request_failed",
                        "request_id": request_id,
                        "method": scope["method"],
                        "route": _route_name(scope),
                        "status_code": 500,
                        "duration_ms": _duration_ms(started_at),
                        **safe_exception_details(exc),
                    },
                )
            raise
        else:
            if scope["path"] not in _QUIET_PATHS:
                self.logger.info(
                    "request_completed",
                    extra={
                        "event": "request_completed",
                        "request_id": request_id,
                        "method": scope["method"],
                        "route": _route_name(scope),
                        "status_code": status_code,
                        "duration_ms": _duration_ms(started_at),
                    },
                )


def _route_name(scope: Scope) -> str:
    route = scope.get("route")
    return getattr(route, "path", scope.get("path", "unknown"))


def _duration_ms(started_at: float) -> float:
    return round((time.perf_counter() - started_at) * 1000, 3)
