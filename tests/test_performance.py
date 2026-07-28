import asyncio
from dataclasses import replace
import gzip
from pathlib import Path

import pytest

from app import main
from app.config import settings
from scripts.performance_audit import (
    AuditError,
    compare,
    structural_checks,
    validate_base_url,
    validate_routes,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def performance_settings():
    return replace(
        settings,
        app_env="development",
        allowed_hosts=("testserver", "localhost"),
        enable_docs=False,
        enable_security_headers=True,
        base_url="http://testserver",
        database_url=None,
        db_host=None,
        db_name=None,
        db_user=None,
        db_password=None,
    )


def asgi_get(application, target, *, request_headers=None):
    async def run():
        messages = []
        received = False

        async def receive():
            nonlocal received
            if not received:
                received = True
                return {"type": "http.request", "body": b"", "more_body": False}
            return {"type": "http.disconnect"}

        async def send(message):
            messages.append(message)

        path, separator, query = target.partition("?")
        headers = [(b"host", b"testserver")]
        headers.extend(
            (name.lower().encode("ascii"), value.encode("ascii"))
            for name, value in (request_headers or {}).items()
        )
        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode("ascii"),
            "query_string": query.encode("ascii") if separator else b"",
            "headers": headers,
            "client": ("127.0.0.1", 50000),
            "server": ("testserver", 80),
            "root_path": "",
        }
        await application(scope, receive, send)
        start = next(item for item in messages if item["type"] == "http.response.start")
        response_headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in start["headers"]
        }
        body = b"".join(
            item.get("body", b"")
            for item in messages
            if item["type"] == "http.response.body"
        )
        return start["status"], response_headers, body

    return asyncio.run(run())


def test_versioned_static_assets_are_immutable_and_conditional():
    application = main.create_app(performance_settings())
    target = "/static/js/main.js?v=10"

    status, headers, body = asgi_get(application, target)

    assert status == 200
    assert body
    assert headers["cache-control"] == "public, max-age=31536000, immutable"
    assert headers["etag"]
    assert headers["last-modified"]

    status, revalidated_headers, revalidated_body = asgi_get(
        application,
        target,
        request_headers={"if-none-match": headers["etag"]},
    )

    assert status == 304
    assert revalidated_body == b""
    assert revalidated_headers["cache-control"] == headers["cache-control"]


def test_unversioned_static_assets_have_short_cache_and_webp_type():
    application = main.create_app(performance_settings())

    status, headers, _ = asgi_get(
        application,
        "/static/images/hero-main-960.webp",
        request_headers={"accept-encoding": "gzip"},
    )

    assert status == 200
    assert headers["cache-control"] == (
        "public, max-age=86400, stale-while-revalidate=604800"
    )
    assert headers["content-type"] == "image/webp"
    assert "content-encoding" not in headers


def test_large_html_and_css_are_gzipped(monkeypatch):
    async def featured(*_args, **_kwargs):
        return []

    async def faq_items(*_args, **_kwargs):
        return []

    monkeypatch.setattr(main, "get_featured_competitions", featured)
    monkeypatch.setattr(main, "get_faq_items", faq_items)
    application = main.create_app(performance_settings())
    request_headers = {"accept-encoding": "gzip"}

    html_status, html_headers, html_body = asgi_get(
        application,
        "/",
        request_headers=request_headers,
    )
    css_status, css_headers, css_body = asgi_get(
        application,
        "/static/css/components.css?v=10",
        request_headers=request_headers,
    )

    assert html_status == css_status == 200
    assert html_headers["content-encoding"] == "gzip"
    assert css_headers["content-encoding"] == "gzip"
    assert "accept-encoding" in html_headers["vary"].casefold()
    assert "accept-encoding" in css_headers["vary"].casefold()
    assert b"<!doctype html>" in gzip.decompress(html_body)
    assert b".competition-card" in gzip.decompress(css_body)


def test_hero_content_is_visible_before_javascript_reveal_runs():
    css = (PROJECT_ROOT / "static/css/pages.css").read_text(encoding="utf-8")
    javascript = (PROJECT_ROOT / "static/js/main.js").read_text(encoding="utf-8")

    assert '[data-reveal="hero"]:not(.is-revealed)' in css
    assert "heroRevealItems.forEach(reveal);" in javascript
    assert "requestAnimationFrame(() => heroRevealItems.forEach(reveal))" not in javascript


def test_fetch_priority_is_limited_to_confirmed_lcp_images():
    index = (PROJECT_ROOT / "templates/index.html").read_text(encoding="utf-8")
    catalog = (PROJECT_ROOT / "templates/competitions.html").read_text(encoding="utf-8")
    faq = (PROJECT_ROOT / "templates/faq.html").read_text(encoding="utf-8")
    card = (
        PROJECT_ROOT / "templates/components/competition_card.html"
    ).read_text(encoding="utf-8")
    detail = (
        PROJECT_ROOT / "templates/competition_detail.html"
    ).read_text(encoding="utf-8")

    assert index.count('fetchpriority="high"') == 1
    assert catalog.count('fetchpriority="high"') == 1
    assert faq.count('fetchpriority="high"') == 1
    assert 'fetchpriority="high"' not in card
    assert 'fetchpriority="high"' not in detail


def test_current_assets_stay_within_deterministic_budget():
    result = structural_checks(root=PROJECT_ROOT)

    assert result["passed"] is True
    assert result["failures"] == []


def test_audit_input_is_same_origin_and_explicit():
    assert validate_base_url("http://127.0.0.1:8000") == "http://127.0.0.1:8000"
    assert validate_routes(["/", "/faq", "/faq"]) == ["/", "/faq"]

    with pytest.raises(AuditError, match=r"HTTP\(S\) origin"):
        validate_base_url("https://user:password@example.test/path")
    with pytest.raises(AuditError, match="same-origin"):
        validate_routes(["https://example.test/"])


def test_audit_comparison_reports_absolute_and_percent_delta():
    before = {
        "base_url": "http://before.test",
        "pages": [{"path": "/", "ttfb_ms": 20, "cls": 0}],
    }
    after = {
        "base_url": "http://after.test",
        "pages": [{"path": "/", "ttfb_ms": 15, "cls": 0}],
    }

    result = compare(before, after)
    ttfb = result["pages"][0]["metrics"]["ttfb_ms"]

    assert ttfb == {
        "before": 20,
        "after": 15,
        "delta": -5.0,
        "percent": -25.0,
    }

def test_audit_comparison_flags_significant_deterministic_regression():
    before = {
        "base_url": "http://before.test",
        "pages": [{"path": "/", "transferred_bytes": 1000, "request_count": 10}],
    }
    after = {
        "base_url": "http://after.test",
        "pages": [{"path": "/", "transferred_bytes": 1200, "request_count": 10}],
    }

    result = compare(before, after)

    assert result["regressions"] == [
        "/: transferred_bytes increased by 20.0%"
    ]
