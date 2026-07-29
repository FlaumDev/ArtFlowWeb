import asyncio
import json
import re
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import Request
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import main
from app.cache import ApplicationCaches
from app.config import settings
from app.database import DatabaseUnavailableError
from app.repositories import competitions as competitions_repository
from app.repositories import faq as faq_repository
from app.routers import competitions as competition_routes
from app.routers import faq as faq_routes
from app.services import competitions as competitions_service
from app.site_content import get_site_content, load_site_content


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def make_settings(*, production=False, https=False, docs=None):
    return replace(
        settings,
        app_env="production" if production else "development",
        allowed_hosts=("testserver", "localhost"),
        enable_docs=(not production if docs is None else docs),
        enable_security_headers=True,
        base_url=(
            "https://example.test"
            if https
            else "http://127.0.0.1:8000"
        ),
    )


def asgi_get(application, path, *, host="testserver"):
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

        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": [(b"host", host.encode())],
            "client": ("127.0.0.1", 50000),
            "server": (host, 80),
            "root_path": "",
        }
        await application(scope, receive, send)
        start = next(item for item in messages if item["type"] == "http.response.start")
        body = b"".join(
            item.get("body", b"")
            for item in messages
            if item["type"] == "http.response.body"
        )
        headers = {
            key.decode().lower(): value.decode()
            for key, value in start["headers"]
        }
        return start["status"], headers, body

    return asyncio.run(run())


def request_for(path="/"):
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": [(b"host", b"testserver")],
            "client": ("test", 50000),
            "server": ("testserver", 80),
            "root_path": "",
            "app": main.app,
        }
    )


def sample_competition():
    return {
        "id": 7,
        "name": "ArtFlow Test",
        "short_description": "Творческий конкурс.",
        "description": "Описание события.",
        "event_date": "05.09.2026",
        "application_deadline": "01.09.2026",
        "city": "Алматы",
        "place": "Сцена",
        "directions": ["Вокал"],
        "poster_url": "https://cdn.example.test/poster.webp",
        "rules_url": "https://cdn.example.test/rules.pdf",
        "price": "12 000 ₸",
        "registration_is_open": True,
        "telegram_url": "https://t.me/ArtFlowBot?start=competition_7",
    }


def write_content(tmp_path, content):
    path = tmp_path / "content.json"
    path.write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")
    return path


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_production_disables_docs_when_setting_is_false(path):
    application = main.create_app(make_settings(production=True, docs=False))
    assert asgi_get(application, path)[0] == 404


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_production_docs_fail_closed_when_setting_is_true(path):
    application = main.create_app(make_settings(production=True, docs=True))
    assert asgi_get(application, path)[0] == 404


def test_development_keeps_docs_when_setting_is_true():
    application = main.create_app(make_settings(production=False, docs=True))
    status, headers, _ = asgi_get(application, "/docs")
    assert status == 200
    assert "content-security-policy" in headers
    assert "https://cdn.jsdelivr.net" in headers["content-security-policy"]
    assert asgi_get(application, "/openapi.json")[0] == 200


def test_allowed_host_passes():
    assert asgi_get(main.create_app(make_settings()), "/health")[0] == 200


def test_forbidden_host_returns_400():
    app = main.create_app(make_settings())
    assert asgi_get(app, "/health", host="evil.example")[0] == 400


def test_csp_is_present():
    _, headers, _ = asgi_get(main.create_app(make_settings()), "/health")
    assert "default-src 'self'" in headers["content-security-policy"]


def test_csp_rejects_unsafe_eval():
    _, headers, _ = asgi_get(main.create_app(make_settings()), "/health")
    assert "unsafe-eval" not in headers["content-security-policy"]


def test_csp_rejects_unsafe_inline():
    _, headers, _ = asgi_get(main.create_app(make_settings()), "/health")
    assert "unsafe-inline" not in headers["content-security-policy"]


def test_public_csp_does_not_allow_data_urls():
    _, headers, _ = asgi_get(main.create_app(make_settings()), "/health")
    assert "data:" not in headers["content-security-policy"]


def test_nosniff_header():
    _, headers, _ = asgi_get(main.create_app(make_settings()), "/health")
    assert headers["x-content-type-options"] == "nosniff"


def test_application_response_has_request_id():
    _, headers, _ = asgi_get(main.create_app(make_settings()), "/health")
    assert re.fullmatch(r"[0-9a-f]{32}", headers["x-request-id"])


@pytest.mark.parametrize(
        ("path", "content_type"),
        [
            ("/static/css/base.css", "text/css"),
            ("/static/css/components.css", "text/css"),
            ("/static/css/pages.css", "text/css"),
            ("/static/css/responsive.css", "text/css"),
            ("/static/js/main.js", "text/javascript"),
            ("/static/images/artflow-logo.png", "image/png"),
            ("/static/images/artflow-logo-512.png", "image/png"),
        ],
)
def test_static_assets_receive_nosniff(path, content_type):
    status, headers, _ = asgi_get(main.create_app(make_settings()), path)
    assert status == 200
    assert headers["content-type"].startswith(content_type)
    assert headers["x-content-type-options"] == "nosniff"


def test_html_receives_full_security_header_set():
    status, headers, _ = asgi_get(
        main.create_app(make_settings()),
        "/missing",
    )
    assert status == 404
    assert headers["x-content-type-options"] == "nosniff"
    assert "default-src 'self'" in headers["content-security-policy"]
    assert headers["referrer-policy"] == "no-referrer"
    assert headers["x-frame-options"] == "DENY"
    assert "camera=()" in headers["permissions-policy"]


def test_referrer_policy_header():
    _, headers, _ = asgi_get(main.create_app(make_settings()), "/health")
    assert headers["referrer-policy"] == "no-referrer"


def test_frame_options_header():
    _, headers, _ = asgi_get(main.create_app(make_settings()), "/health")
    assert headers["x-frame-options"] == "DENY"


def test_permissions_policy_header():
    _, headers, _ = asgi_get(main.create_app(make_settings()), "/health")
    assert "camera=()" in headers["permissions-policy"]


def test_hsts_absent_in_development():
    _, headers, _ = asgi_get(main.create_app(make_settings()), "/health")
    assert "strict-transport-security" not in headers


def test_hsts_only_for_production_https():
    app = main.create_app(make_settings(production=True, https=True))
    _, headers, _ = asgi_get(app, "/health")
    assert headers["strict-transport-security"] == "max-age=31536000"
    local_settings = replace(
        make_settings(production=True, https=True),
        base_url="https://localhost",
    )
    assert local_settings.public_https_base_url is None

    malformed_port_settings = replace(
        make_settings(production=True, https=True),
        base_url="https://example.test:not-a-port",
    )
    _, malformed_headers, _ = asgi_get(
        main.create_app(malformed_port_settings),
        "/health",
    )
    assert "strict-transport-security" not in malformed_headers


@pytest.mark.parametrize(
    "invalid_base_url",
    [
        "https://example.test\n.evil.test",
        "https://exam ple.test",
        "https://user:password@example.test",
        "https://10.0.0.5",
    ],
)
def test_invalid_production_origin_does_not_enable_hsts(invalid_base_url):
    app_settings = replace(
        make_settings(production=True, https=True),
        base_url=invalid_base_url,
    )
    assert app_settings.public_https_base_url is None


def test_robots_txt_is_public_and_non_sensitive():
    status, headers, body = asgi_get(main.create_app(make_settings()), "/robots.txt")
    assert status == 200
    assert headers["content-type"].startswith("text/plain")
    assert headers["x-content-type-options"] == "nosniff"
    assert b"User-agent: *" in body
    assert b"Disallow: /openapi.json" in body


def test_jinja_escapes_script(monkeypatch):
    async def faq_items(database_pool=None, cache=None):
        return [{"id": 1, "question": "<script>alert(1)</script>", "answer": "ok"}]

    monkeypatch.setattr(faq_routes, "get_faq_items", faq_items)
    response = asyncio.run(faq_routes.faq(request_for("/faq")))
    body = response.body.decode()
    assert "<script>alert(1)</script>" not in body
    assert "&lt;script&gt;" in body


def test_javascript_poster_url_is_rejected():
    assert competitions_service._http_url("javascript:alert(1)") is None


def test_http_poster_url_is_rejected_in_production(monkeypatch):
    monkeypatch.setattr(competitions_service, "settings", make_settings(production=True))
    assert competitions_service._http_url("http://cdn.example.test/poster") is None


def test_https_poster_url_is_allowed(monkeypatch):
    monkeypatch.setattr(competitions_service, "settings", make_settings(production=True))
    url = "https://cdn.example.test/poster"
    assert competitions_service._http_url(url) == url


def test_external_poster_has_no_referrer_policy():
    templates = (PROJECT_ROOT / "templates").rglob("*.html")
    source = "\n".join(path.read_text(encoding="utf-8") for path in templates)
    assert 'referrerpolicy="no-referrer"' in source


def test_foreign_whatsapp_host_is_rejected(tmp_path):
    content = load_site_content(write_content(tmp_path, {"contacts": {"organizers": [{"name": "A", "whatsapp_url": "https://evil.test/x"}]}}))
    assert content["contacts"]["organizers"][0]["whatsapp_url"] == ""


def test_foreign_telegram_host_is_rejected(tmp_path):
    content = load_site_content(write_content(tmp_path, {"contacts": {"organizers": [{"name": "A", "telegram_url": "https://evil.test/x"}]}}))
    assert content["contacts"]["organizers"][0]["telegram_url"] == ""


def test_foreign_instagram_host_is_rejected(tmp_path):
    content = load_site_content(write_content(tmp_path, {"contacts": {"instagram": {"url": "https://evil.test/artflow"}}}))
    assert content["contacts"]["instagram"]["url"] == ""


@pytest.mark.parametrize(
    "telegram_url",
    [
        "javascript:alert(1)",
        "data:text/html,unsafe",
        "https://user:password@t.me/organizer",
        "https://t.me:not-a-port/organizer",
        "https://t.me/organizer\x7f",
    ],
)
def test_unsafe_social_urls_are_rejected(tmp_path, telegram_url):
    content = load_site_content(
        write_content(
            tmp_path,
            {
                "contacts": {
                    "organizers": [
                        {"name": "A", "telegram_url": telegram_url}
                    ]
                }
            },
        )
    )
    assert content["contacts"]["organizers"][0]["telegram_url"] == ""


def test_email_with_crlf_is_rejected(tmp_path):
    content = load_site_content(write_content(tmp_path, {"contacts": {"email": "hello@example.test\r\nBcc:evil@example.test"}}))
    assert content["contacts"]["email"] == ""


@pytest.mark.parametrize(
    "email",
    [
        "hello%0d%0aBcc:evil@example.test",
        "hello@example.test?subject=unsafe",
    ],
)
def test_email_with_injected_mailto_fields_is_rejected(tmp_path, email):
    content = load_site_content(
        write_content(tmp_path, {"contacts": {"email": email}})
    )
    assert content["contacts"]["email"] == ""


def test_competition_deep_link_contract_is_unchanged():
    assert competitions_service.build_competition_telegram_url("ArtFlowBot", 7) == "https://t.me/ArtFlowBot?start=competition_7"


def test_repositories_contain_select_only():
    queries = [
        value
        for module in (competitions_repository, faq_repository)
        for name, value in vars(module).items()
        if name.endswith("_SQL") and isinstance(value, str)
    ]
    forbidden = {"INSERT", "UPDATE", "DELETE", "CREATE", "ALTER", "DROP", "TRUNCATE"}
    assert queries
    for query in queries:
        words = set(re.findall(r"[A-Z_]+", query.upper()))
        assert " ".join(query.upper().split()).startswith("SELECT ")
        assert not forbidden.intersection(words)


def test_cache_returns_data_within_ttl(monkeypatch):
    calls = 0

    async def rows(limit=None, *, pool=None):
        nonlocal calls
        calls += 1
        return []

    monkeypatch.setattr(competitions_repository, "get_published_competitions", rows)
    cache = ApplicationCaches().competitions

    async def load_twice():
        await competitions_service.get_competitions(cache=cache)
        await competitions_service.get_competitions(cache=cache)

    asyncio.run(load_twice())
    assert calls == 1


def test_database_error_is_not_cached_forever(monkeypatch):
    calls = 0

    async def rows(limit=None, *, pool=None):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise DatabaseUnavailableError("temporary")
        return []

    monkeypatch.setattr(competitions_repository, "get_published_competitions", rows)
    cache = ApplicationCaches().competitions

    async def load_twice():
        with pytest.raises(DatabaseUnavailableError):
            await competitions_service.get_competitions(cache=cache)
        return await competitions_service.get_competitions(cache=cache)

    assert asyncio.run(load_twice()) == []
    assert calls == 2


def test_health_db_does_not_reveal_secrets(monkeypatch):
    async def unavailable(_pool):
        raise DatabaseUnavailableError("postgres://user:SECRET@host/database")

    monkeypatch.setattr(main, "check_database_connection", unavailable)
    response = asyncio.run(main.health_db(request_for("/health/db")))
    assert response.status_code == 503
    assert b"SECRET" not in response.body
    assert b"postgres" not in response.body


def test_500_page_hides_traceback():
    response = asyncio.run(main.server_error(request_for("/500"), RuntimeError("SECRET_DSN")))
    body = response.body.decode()
    assert response.status_code == 500
    assert "Traceback" not in body
    assert "SECRET_DSN" not in body
    assert response.headers["x-content-type-options"] == "nosniff"


def test_image_extensions_match_file_signatures():
    for path in (PROJECT_ROOT / "static" / "images").iterdir():
        if path.suffix.lower() == ".png":
            assert path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
        if path.suffix.lower() == ".webp":
            data = path.read_bytes()[:12]
            assert data.startswith(b"RIFF") and data[8:12] == b"WEBP"


def test_organizer_webp_are_available_to_templates():
    organizers = get_site_content()["contacts"]["organizers"]
    assert [item["photo"] for item in organizers] == [
        "/static/images/organizer-1.webp",
        "/static/images/organizer-2.webp",
    ]
    assert all((PROJECT_ROOT / item["photo"].lstrip("/")).is_file() for item in organizers)


def test_home_has_one_final_contact_section(monkeypatch):
    async def no_competitions(
        limit=3,
        app_settings=None,
        database_pool=None,
        cache=None,
    ):
        return []

    async def no_faq(database_pool=None, cache=None):
        return []

    monkeypatch.setattr(main, "get_featured_competitions", no_competitions)
    monkeypatch.setattr(main, "get_faq_items", no_faq)
    body = asyncio.run(main.index(request_for("/"))).body.decode()
    assert body.count('class="contact-section"') == 1


def test_detail_does_not_render_all_contact_blocks(monkeypatch):
    async def competition(
        _competition_id,
        app_settings=None,
        database_pool=None,
        cache=None,
    ):
        return sample_competition()

    monkeypatch.setattr(competition_routes, "get_competition_by_id", competition)
    body = asyncio.run(competition_routes.competition_detail(request_for("/competitions/7"), 7)).body.decode()
    assert body.count('class="event-help"') == 1
    assert 'class="contact-section"' not in body
    assert 'class="floating-contact"' not in body

    async def closed_competition(
        _competition_id,
        app_settings=None,
        database_pool=None,
        cache=None,
    ):
        item = sample_competition()
        item["registration_is_open"] = False
        return item

    monkeypatch.setattr(
        competition_routes,
        "get_competition_by_id",
        closed_competition,
    )
    closed_body = asyncio.run(
        competition_routes.competition_detail(
            request_for("/competitions/7"),
            7,
        )
    ).body.decode()
    assert "https://t.me/ArtFlowBot?start=competition_7" not in closed_body


def test_404_and_503_do_not_render_floating_contact(monkeypatch):
    not_found = asyncio.run(main.not_found(request_for("/missing"), StarletteHTTPException(404)))

    async def unavailable(
        _competition_id,
        app_settings=None,
        database_pool=None,
        cache=None,
    ):
        raise DatabaseUnavailableError("offline")

    monkeypatch.setattr(competition_routes, "get_competition_by_id", unavailable)
    unavailable_response = asyncio.run(competition_routes.competition_detail(request_for("/competitions/7"), 7))
    assert 'class="floating-contact"' not in not_found.body.decode()
    assert 'class="floating-contact"' not in unavailable_response.body.decode()


def test_all_blank_target_links_are_isolated():
    for path in (PROJECT_ROOT / "templates").rglob("*.html"):
        source = path.read_text(encoding="utf-8")
        for tag in re.findall(r"<a\b[^>]*target=\"_blank\"[^>]*>", source, re.DOTALL):
            assert re.search(r'rel="[^"]*\bnoopener\b[^"]*\bnoreferrer\b[^"]*"', tag), f"Unsafe link in {path}"


def test_detail_help_fragment_requires_organizer_section(monkeypatch):
    async def competition(
        _competition_id,
        app_settings=None,
        database_pool=None,
        cache=None,
    ):
        return sample_competition()

    async def no_related(*args, **kwargs):
        return []

    site_content = get_site_content()
    site_content["contacts"]["organizers"] = []
    site_content["contacts"]["email"] = "help@example.test"
    site_content["has_contacts"] = True
    monkeypatch.setattr(
        competition_routes,
        "get_competition_by_id",
        competition,
    )
    monkeypatch.setattr(
        competition_routes,
        "get_related_competitions",
        no_related,
    )
    monkeypatch.setattr(
        competition_routes,
        "get_site_content",
        lambda: site_content,
    )

    response = asyncio.run(
        competition_routes.competition_detail(
            request_for("/competitions/7"),
            "7",
        )
    )
    body = response.body.decode()
    assert 'href="#event-help"' not in body
    assert 'id="event-help"' not in body
