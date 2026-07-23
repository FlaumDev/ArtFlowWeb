import asyncio
import io
import json
import logging
from dataclasses import replace

import pytest

from app.config import settings
from app.observability import (
    RequestLoggingMiddleware,
    create_application_logger,
    disable_duplicate_uvicorn_access_log,
)


def run_request(middleware, path="/competitions/7"):
    async def run():
        messages = []

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            messages.append(message)

        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "https",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"secret=DO_NOT_LOG",
            "headers": [],
            "client": ("127.0.0.1", 50000),
            "server": ("testserver", 443),
            "root_path": "",
        }
        await middleware(scope, receive, send)
        return messages

    return asyncio.run(run())


def response_headers(messages):
    start = next(item for item in messages if item["type"] == "http.response.start")
    return {key.decode().lower(): value.decode() for key, value in start["headers"]}


def test_production_request_log_is_structured_and_safe():
    stream = io.StringIO()
    app_settings = replace(settings, app_env="production")
    logger = create_application_logger(
        app_settings,
        name="artflow.test.production",
        stream=stream,
    )

    async def application(scope, receive, send):
        scope["route"] = type("Route", (), {"path": "/competitions/{competition_id}"})()
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"text/html")],
            }
        )
        await send({"type": "http.response.body", "body": b"ok"})

    messages = run_request(RequestLoggingMiddleware(application, logger=logger))
    headers = response_headers(messages)
    payload = json.loads(stream.getvalue())

    assert len(headers["x-request-id"]) == 32
    assert payload["event"] == "request_completed"
    assert payload["route"] == "/competitions/{competition_id}"
    assert payload["status_code"] == 200
    assert isinstance(payload["duration_ms"], float)
    assert "DO_NOT_LOG" not in stream.getvalue()


def test_health_requests_are_not_written_to_application_access_log():
    stream = io.StringIO()
    logger = create_application_logger(
        settings,
        name="artflow.test.health",
        stream=stream,
    )

    async def application(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    messages = run_request(
        RequestLoggingMiddleware(application, logger=logger),
        path="/health",
    )
    assert "x-request-id" in response_headers(messages)
    assert stream.getvalue() == ""


def test_exception_log_omits_exception_message_and_secrets():
    stream = io.StringIO()
    app_settings = replace(settings, app_env="production")
    logger = create_application_logger(
        app_settings,
        name="artflow.test.exception",
        stream=stream,
    )

    async def application(scope, receive, send):
        raise RuntimeError(
            "postgresql://user:DO_NOT_EXPOSE@database.example/artflow"
        )

    middleware = RequestLoggingMiddleware(application, logger=logger)
    with pytest.raises(RuntimeError):
        run_request(middleware)

    payload = json.loads(stream.getvalue())
    assert payload["event"] == "request_failed"
    assert payload["exception_type"] == "RuntimeError"
    assert payload["exception_stack"]
    assert "DO_NOT_EXPOSE" not in stream.getvalue()
    assert "postgresql" not in stream.getvalue()


def test_uvicorn_access_log_is_disabled_without_disabling_errors():
    access_logger = logging.getLogger("uvicorn.access")
    error_logger = logging.getLogger("uvicorn.error")
    previous_access_state = access_logger.disabled
    previous_error_state = error_logger.disabled
    try:
        access_logger.disabled = False
        error_logger.disabled = False
        disable_duplicate_uvicorn_access_log()
        assert access_logger.disabled is True
        assert error_logger.disabled is False
    finally:
        access_logger.disabled = previous_access_state
        error_logger.disabled = previous_error_state
