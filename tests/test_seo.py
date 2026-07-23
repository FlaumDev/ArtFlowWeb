import asyncio
from dataclasses import replace
from xml.etree import ElementTree

from fastapi import Request
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import main
from app.config import settings
from app.database import DatabaseUnavailableError


SITEMAP_NAMESPACE = {"sitemap": "http://www.sitemaps.org/schemas/sitemap/0.9"}


def production_settings(*, base_url: str = "https://artflow.example.test"):
    return replace(
        settings,
        app_env="production",
        base_url=base_url,
        allowed_hosts=("testserver",),
        enable_docs=False,
    )


def request_for(application, path: str) -> Request:
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "https",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": [(b"host", b"testserver")],
            "client": ("test", 50000),
            "server": ("testserver", 443),
            "root_path": "",
            "app": application,
        }
    )


def sitemap_locations(response) -> list[str]:
    root = ElementTree.fromstring(response.body)
    return [
        element.text or ""
        for element in root.findall("sitemap:url/sitemap:loc", SITEMAP_NAMESPACE)
    ]


def test_sitemap_uses_published_service_pool_and_cache(monkeypatch):
    application = main.create_app(production_settings())
    database_pool = object()
    application.state.database_pool = database_pool
    received = {}

    async def published_competitions(
        app_settings=None,
        *,
        database_pool=None,
        cache=None,
    ):
        received.update(
            settings=app_settings,
            pool=database_pool,
            cache=cache,
        )
        return [{"id": 7}, {"id": 9}, {"id": 0}, {"id": "10"}]

    monkeypatch.setattr(main, "get_competitions", published_competitions)
    response = asyncio.run(
        main.sitemap(request_for(application, "/sitemap.xml"))
    )

    assert response.headers["content-type"].startswith("application/xml")
    assert sitemap_locations(response) == [
        "https://artflow.example.test/",
        "https://artflow.example.test/competitions",
        "https://artflow.example.test/faq",
        "https://artflow.example.test/competitions/7",
        "https://artflow.example.test/competitions/9",
    ]
    assert received == {
        "settings": application.state.settings,
        "pool": database_pool,
        "cache": application.state.caches.competitions,
    }


def test_sitemap_falls_back_to_static_pages_when_database_is_unavailable(
    monkeypatch,
):
    application = main.create_app(production_settings())

    async def unavailable(*args, **kwargs):
        raise DatabaseUnavailableError("database details must stay private")

    monkeypatch.setattr(main, "get_competitions", unavailable)
    response = asyncio.run(
        main.sitemap(request_for(application, "/sitemap.xml"))
    )

    assert sitemap_locations(response) == [
        "https://artflow.example.test/",
        "https://artflow.example.test/competitions",
        "https://artflow.example.test/faq",
    ]
    assert b"database details" not in response.body


def test_sitemap_never_uses_local_development_origin(monkeypatch):
    application = main.create_app(
        replace(
            settings,
            app_env="development",
            base_url="http://localhost:8000",
            allowed_hosts=("testserver",),
        )
    )

    async def must_not_load(*args, **kwargs):
        raise AssertionError("development sitemap must not query PostgreSQL")

    monkeypatch.setattr(main, "get_competitions", must_not_load)
    response = asyncio.run(
        main.sitemap(request_for(application, "/sitemap.xml"))
    )

    assert sitemap_locations(response) == []
    assert b"localhost" not in response.body


def test_robots_adds_sitemap_only_for_public_https_base_url():
    production_app = main.create_app(production_settings())
    production_response = asyncio.run(
        main.robots(request_for(production_app, "/robots.txt"))
    )
    production_body = production_response.body.decode()

    assert (
        "Sitemap: https://artflow.example.test/sitemap.xml"
        in production_body
    )
    assert "Disallow: /docs" in production_body
    assert "Disallow: /openapi.json" in production_body

    development_app = main.create_app(
        replace(
            settings,
            app_env="development",
            base_url="http://localhost:8000",
            allowed_hosts=("testserver",),
        )
    )
    development_response = asyncio.run(
        main.robots(request_for(development_app, "/robots.txt"))
    )
    assert "Sitemap:" not in development_response.body.decode()


def test_html_contains_canonical_open_graph_and_twitter_metadata():
    application = main.create_app(production_settings())
    response = asyncio.run(
        main.not_found(
            request_for(application, "/missing"),
            StarletteHTTPException(status_code=404),
        )
    )
    body = response.body.decode()

    assert (
        '<meta property="og:url" '
        'content="https://artflow.example.test/missing">'
    ) in body
    assert '<meta name="twitter:card" content="summary_large_image">' in body
    assert '<meta name="twitter:title"' in body
    assert '<meta name="twitter:description"' in body
    assert (
        '<meta name="twitter:image" '
        'content="https://artflow.example.test/static/'
    ) in body
    assert "localhost" not in body
