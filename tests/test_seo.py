import asyncio
import json
import re
from dataclasses import replace
from html import unescape
from xml.etree import ElementTree

import pytest
from fastapi import Request
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import main
from app.config import settings
from app.database import DatabaseUnavailableError
from app.routers import competitions as competition_routes
from app.routers import faq as faq_routes
from app.seo import (
    DESCRIPTION_LIMIT,
    competition_structured_data,
    meta_description,
    plain_text,
)


CANONICAL_BASE_URL = "https://artflowfest.com"
SITEMAP_NAMESPACE = {"sitemap": "http://www.sitemaps.org/schemas/sitemap/0.9"}


def production_settings(*, base_url: str = CANONICAL_BASE_URL, docs: bool = False):
    return replace(
        settings,
        app_env="production",
        base_url=base_url,
        allowed_hosts=("testserver",),
        enable_docs=docs,
    )


def request_for(application, path: str, *, query_string: bytes = b"") -> Request:
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "https",
            "path": path,
            "raw_path": path.encode(),
            "query_string": query_string,
            "headers": [(b"host", b"testserver")],
            "client": ("test", 50000),
            "server": ("testserver", 443),
            "root_path": "",
            "app": application,
        }
    )


def asgi_get(application, path: str, *, query_string: bytes = b""):
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
            "scheme": "https",
            "path": path,
            "raw_path": path.encode(),
            "query_string": query_string,
            "headers": [(b"host", b"testserver")],
            "client": ("127.0.0.1", 50000),
            "server": ("testserver", 443),
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


def sample_competition(**overrides):
    item = {
        "id": 7,
        "name": "Весенний фестиваль искусств",
        "short_description": "Сценическое событие для солистов и коллективов.",
        "description": "Участники представляют подготовленные творческие номера.",
        "event_date": "05.09.2026",
        "application_deadline": "01.09.2026",
        "city": "Алматы",
        "place": "Дворец творчества",
        "directions": ["Вокал", "Хореография"],
        "poster_url": "https://cdn.example.test/posters/artflow.webp",
        "rules_url": "https://cdn.example.test/rules/artflow.pdf",
        "price": "12 000 ₸",
        "registration_is_open": True,
        "telegram_url": "https://t.me/ArtFlowBot?start=competition_7",
        "is_published": True,
        "seo_source": {
            "name": "Весенний фестиваль искусств",
            "description": "Сценическое событие для солистов и коллективов.",
            "event_date": "2026-09-05",
            "city": "Алматы",
            "place": "Дворец творчества",
        },
    }
    item.update(overrides)
    return item


def install_public_data(monkeypatch, *, competitions=None, faq_items=None):
    items = [sample_competition()] if competitions is None else competitions
    questions = (
        [{"id": 1, "question": "Как подать заявку?", "answer": "В Telegram."}]
        if faq_items is None
        else faq_items
    )

    async def featured(*args, **kwargs):
        return items[:3]

    async def all_competitions(*args, **kwargs):
        return items

    async def competition_by_id(competition_id, *args, **kwargs):
        return next(
            (
                item
                for item in items
                if item.get("id") == competition_id
                and item.get("is_published") is not False
            ),
            None,
        )

    async def faq(*args, **kwargs):
        return questions

    monkeypatch.setattr(main, "get_featured_competitions", featured)
    monkeypatch.setattr(main, "get_faq_items", faq)
    monkeypatch.setattr(main, "get_competitions", all_competitions)
    monkeypatch.setattr(competition_routes, "get_competitions", all_competitions)
    monkeypatch.setattr(competition_routes, "get_competition_by_id", competition_by_id)
    monkeypatch.setattr(faq_routes, "get_faq_items", faq)


def html_response(application, path: str, *, query_string: bytes = b""):
    status, headers, body = asgi_get(application, path, query_string=query_string)
    return status, headers, body.decode()


def meta_content(body: str, *, name: str | None = None, prop: str | None = None):
    attribute = "name" if name is not None else "property"
    value = name if name is not None else prop
    match = re.search(
        rf'<meta\s+{attribute}="{re.escape(value or "")}"\s+content="([^"]*)">',
        body,
    )
    return unescape(match.group(1)) if match else None


def canonical_url(body: str) -> str | None:
    match = re.search(r'<link rel="canonical" href="([^"]+)">', body)
    return unescape(match.group(1)) if match else None


def page_title(body: str) -> str:
    match = re.search(r"<title>(.*?)</title>", body, re.DOTALL)
    assert match
    return unescape(match.group(1)).strip()


def structured_data(body: str) -> list[dict]:
    blocks = re.findall(
        r'<script type="application/ld\+json">(.*?)</script>',
        body,
        re.DOTALL,
    )
    return [json.loads(unescape(block)) for block in blocks]


def sitemap_locations(response) -> list[str]:
    root = ElementTree.fromstring(response.body)
    return [
        element.text or ""
        for element in root.findall("sitemap:url/sitemap:loc", SITEMAP_NAMESPACE)
    ]


def test_text_cleanup_removes_html_scripts_controls_and_truncates_words():
    source = "<p>Текст <b>описания</b></p><script>alert(1)</script>\x00  дальше"
    assert plain_text(source) == "Текст описания дальше"
    description = meta_description("слово " * 100)
    assert len(description) <= DESCRIPTION_LIMIT + 1
    assert description.endswith("…")


@pytest.mark.parametrize(
    ("path", "expected_title", "expected_canonical"),
    [
        (
            "/",
            "ArtFlow — конкурсы и фестивали для юных талантов",
            f"{CANONICAL_BASE_URL}/",
        ),
        (
            "/competitions",
            "Конкурсы и фестивали ArtFlow — подать заявку онлайн",
            f"{CANONICAL_BASE_URL}/competitions",
        ),
        (
            "/faq",
            "Частые вопросы об участии в конкурсах | ArtFlow",
            f"{CANONICAL_BASE_URL}/faq",
        ),
    ],
)
def test_public_pages_have_unique_metadata(
    monkeypatch,
    path,
    expected_title,
    expected_canonical,
):
    install_public_data(monkeypatch)
    status, _, body = html_response(main.create_app(production_settings()), path)
    assert status == 200
    assert page_title(body) == expected_title
    assert meta_content(body, name="description")
    assert meta_content(body, name="robots") == "index, follow"
    assert canonical_url(body) == expected_canonical
    assert meta_content(body, prop="og:url") == expected_canonical


def test_public_page_titles_and_descriptions_are_distinct(monkeypatch):
    install_public_data(monkeypatch)
    application = main.create_app(production_settings())
    bodies = [html_response(application, path)[2] for path in ("/", "/competitions", "/faq")]
    assert len({page_title(body) for body in bodies}) == 3
    assert len({meta_content(body, name="description") for body in bodies}) == 3


def test_canonical_ignores_query_string(monkeypatch):
    install_public_data(monkeypatch)
    _, _, body = html_response(
        main.create_app(production_settings()),
        "/competitions",
        query_string=b"status=open&city=Almaty#fragment",
    )
    assert canonical_url(body) == f"{CANONICAL_BASE_URL}/competitions"
    assert "?" not in canonical_url(body)
    assert "#" not in canonical_url(body)


def test_homepage_has_full_social_metadata_and_structured_data(monkeypatch):
    install_public_data(monkeypatch)
    _, _, body = html_response(main.create_app(production_settings()), "/")
    assert meta_content(body, prop="og:type") == "website"
    assert meta_content(body, prop="og:title") == page_title(body)
    assert meta_content(body, prop="og:description") == meta_content(
        body, name="description"
    )
    assert meta_content(body, prop="og:site_name") == "ArtFlow"
    assert meta_content(body, prop="og:locale") == "ru_RU"
    assert meta_content(body, prop="og:image").startswith(CANONICAL_BASE_URL)
    assert meta_content(body, name="twitter:card") == "summary_large_image"
    assert meta_content(body, name="twitter:title") == page_title(body)
    assert meta_content(body, name="twitter:description")
    assert meta_content(body, name="twitter:image").startswith(CANONICAL_BASE_URL)

    schemas = {item["@type"]: item for item in structured_data(body)}
    assert schemas["WebSite"]["url"] == f"{CANONICAL_BASE_URL}/"
    assert schemas["WebSite"]["inLanguage"] == "ru"
    assert schemas["Organization"]["name"] == "ArtFlow"
    assert schemas["Organization"]["logo"]["url"].startswith(CANONICAL_BASE_URL)
    assert schemas["Organization"]["sameAs"] == [
        "https://www.instagram.com/art_flow_karina"
    ]


def test_competition_page_has_unique_metadata_and_absolute_social_image(monkeypatch):
    install_public_data(monkeypatch)
    status, _, body = html_response(
        main.create_app(production_settings()),
        "/competitions/7",
    )
    expected_url = f"{CANONICAL_BASE_URL}/competitions/7"
    assert status == 200
    assert page_title(body) == "Весенний фестиваль искусств — условия участия | ArtFlow"
    description = meta_content(body, name="description")
    assert "Сценическое событие" in description
    assert "05.09.2026" in description
    assert "Алматы" in description
    assert canonical_url(body) == expected_url
    assert meta_content(body, prop="og:url") == expected_url
    assert meta_content(body, prop="og:image") == (
        "https://cdn.example.test/posters/artflow.webp"
    )
    assert meta_content(body, name="twitter:card") == "summary_large_image"
    assert meta_content(body, name="twitter:title") == page_title(body)


def test_competition_event_and_breadcrumb_json_ld_use_only_real_fields(monkeypatch):
    install_public_data(monkeypatch)
    _, _, body = html_response(
        main.create_app(production_settings()),
        "/competitions/7",
    )
    schemas = {item["@type"]: item for item in structured_data(body)}
    event = schemas["Event"]
    breadcrumb = schemas["BreadcrumbList"]

    assert event["name"] == "Весенний фестиваль искусств"
    assert event["description"] == "Сценическое событие для солистов и коллективов."
    assert event["startDate"] == "2026-09-05"
    assert event["url"] == f"{CANONICAL_BASE_URL}/competitions/7"
    assert event["image"] == ["https://cdn.example.test/posters/artflow.webp"]
    assert event["location"]["name"] == "Дворец творчества, Алматы"
    assert event["location"]["address"]["addressLocality"] == "Алматы"
    assert event["organizer"] == {
        "@type": "Organization",
        "name": "ArtFlow",
        "url": f"{CANONICAL_BASE_URL}/",
    }
    forbidden = {
        "endDate",
        "eventStatus",
        "eventAttendanceMode",
        "offers",
        "aggregateRating",
        "review",
        "performer",
    }
    assert forbidden.isdisjoint(event)
    assert [item["position"] for item in breadcrumb["itemListElement"]] == [1, 2, 3]
    assert breadcrumb["itemListElement"][-1]["item"] == event["url"]


@pytest.mark.parametrize(
    "missing_field",
    ["name", "description", "event_date", "city_and_place"],
)
def test_event_json_ld_is_omitted_when_real_data_is_insufficient(missing_field):
    competition = sample_competition()
    source = dict(competition["seo_source"])
    if missing_field == "city_and_place":
        source["city"] = None
        source["place"] = None
    else:
        source[missing_field] = None
    competition["seo_source"] = source

    schemas = competition_structured_data(
        competition,
        base_url=CANONICAL_BASE_URL,
        canonical_url=f"{CANONICAL_BASE_URL}/competitions/7",
        image_url=f"{CANONICAL_BASE_URL}/static/images/artflow-logo-512.png",
    )
    assert [item["@type"] for item in schemas] == ["BreadcrumbList"]


def test_json_ld_serialization_cannot_close_script_tag(monkeypatch):
    item = sample_competition(
        name='Фестиваль </script><script>alert("x")</script>',
        seo_source={
            "name": 'Фестиваль </script><script>alert("x")</script>',
            "description": "Описание <b>события</b> </script>",
            "event_date": "2026-09-05",
            "city": "Алматы",
            "place": "Сцена",
        },
    )
    install_public_data(monkeypatch, competitions=[item])
    _, _, body = html_response(
        main.create_app(production_settings()),
        "/competitions/7",
    )
    head = body.split("</head>", 1)[0]
    assert "</script><script>" not in head
    assert 'alert("x")' not in head
    schemas = structured_data(body)
    assert {item["@type"] for item in schemas} == {"BreadcrumbList", "Event"}


def test_html_in_competition_name_is_escaped_and_description_has_no_tags(monkeypatch):
    item = sample_competition(
        name="<b>Фестиваль</b>",
        short_description="<p>Краткое <strong>описание</strong></p>",
        seo_source={
            "name": "<b>Фестиваль</b>",
            "description": "<p>Краткое <strong>описание</strong></p>",
            "event_date": "2026-09-05",
            "city": "Алматы",
            "place": "Сцена",
        },
    )
    install_public_data(monkeypatch, competitions=[item])
    _, _, body = html_response(
        main.create_app(production_settings()),
        "/competitions/7",
    )
    assert "&lt;b&gt;Фестиваль&lt;/b&gt;" in body
    assert page_title(body) == "Фестиваль — условия участия | ArtFlow"
    description = meta_content(body, name="description")
    assert description == "Краткое описание — Дата: 05.09.2026, город: Алматы."
    assert not re.search(r"<[^>]+>", description)


def test_missing_poster_uses_absolute_artflow_fallback(monkeypatch):
    install_public_data(
        monkeypatch,
        competitions=[sample_competition(poster_url=None)],
    )
    _, _, body = html_response(
        main.create_app(production_settings()),
        "/competitions/7",
    )
    fallback = f"{CANONICAL_BASE_URL}/static/images/artflow-logo-512.png"
    assert meta_content(body, prop="og:image") == fallback
    event = next(item for item in structured_data(body) if item["@type"] == "Event")
    assert event["image"] == [fallback]


def test_unpublished_and_unknown_competitions_return_noindex_404(monkeypatch):
    install_public_data(
        monkeypatch,
        competitions=[sample_competition(is_published=False)],
    )
    application = main.create_app(production_settings())
    for path in ("/competitions/7", "/competitions/999"):
        status, _, body = html_response(application, path)
        assert status == 404
        assert meta_content(body, name="robots") == "noindex, nofollow"
        assert canonical_url(body) is None
        assert meta_content(body, prop="og:url") is None


def test_404_and_500_have_noindex_and_no_canonical():
    application = main.create_app(production_settings())
    not_found = asyncio.run(
        main.not_found(
            request_for(application, "/missing"),
            StarletteHTTPException(status_code=404),
        )
    )
    server_error = asyncio.run(
        main.server_error(
            request_for(application, "/broken"),
            RuntimeError("private detail"),
        )
    )
    for response in (not_found, server_error):
        body = response.body.decode()
        assert meta_content(body, name="robots") == "noindex, nofollow"
        assert canonical_url(body) is None
        assert meta_content(body, prop="og:url") is None


@pytest.mark.parametrize("route_name", ["home", "competitions", "faq", "detail"])
def test_database_error_pages_are_noindex_without_canonical(monkeypatch, route_name):
    async def unavailable(*args, **kwargs):
        raise DatabaseUnavailableError("private database detail")

    monkeypatch.setattr(main, "get_featured_competitions", unavailable)
    monkeypatch.setattr(main, "get_faq_items", unavailable)
    monkeypatch.setattr(competition_routes, "get_competitions", unavailable)
    monkeypatch.setattr(competition_routes, "get_competition_by_id", unavailable)
    monkeypatch.setattr(faq_routes, "get_faq_items", unavailable)
    paths = {
        "home": "/",
        "competitions": "/competitions",
        "faq": "/faq",
        "detail": "/competitions/7",
    }
    status, _, body = html_response(
        main.create_app(production_settings()),
        paths[route_name],
    )
    assert status == 503
    assert meta_content(body, name="robots") == "noindex, nofollow"
    assert canonical_url(body) is None


def test_robots_txt_uses_canonical_sitemap_and_allows_public_pages():
    application = main.create_app(production_settings())
    status, headers, body = asgi_get(application, "/robots.txt")
    text = body.decode()
    assert status == 200
    assert headers["content-type"].startswith("text/plain")
    assert "User-agent: *" in text
    assert "Allow: /" in text
    assert f"Sitemap: {CANONICAL_BASE_URL}/sitemap.xml" in text
    assert "Disallow: /competitions" not in text
    assert "Disallow: /faq" not in text
    assert "DATABASE_URL" not in text


def test_robots_omits_sitemap_for_local_development():
    development = replace(
        settings,
        app_env="development",
        base_url="http://localhost:8000",
        allowed_hosts=("testserver",),
    )
    _, _, body = asgi_get(main.create_app(development), "/robots.txt")
    assert "Sitemap:" not in body.decode()


def test_sitemap_uses_published_service_pool_and_cache(monkeypatch):
    application = main.create_app(production_settings())
    database_pool = object()
    application.state.database_pool = database_pool
    received = {}

    async def published_competitions(app_settings=None, *, database_pool=None, cache=None):
        received.update(settings=app_settings, pool=database_pool, cache=cache)
        return [
            {"id": 7, "is_published": True},
            {"id": 9, "is_published": True},
            {"id": 10, "is_published": False},
            {"id": 7, "is_published": True},
            {"id": 0},
            {"id": "11"},
        ]

    monkeypatch.setattr(main, "get_competitions", published_competitions)
    response = asyncio.run(main.sitemap(request_for(application, "/sitemap.xml")))

    assert response.headers["content-type"].startswith("application/xml")
    assert sitemap_locations(response) == [
        f"{CANONICAL_BASE_URL}/",
        f"{CANONICAL_BASE_URL}/competitions",
        f"{CANONICAL_BASE_URL}/faq",
        f"{CANONICAL_BASE_URL}/competitions/7",
        f"{CANONICAL_BASE_URL}/competitions/9",
    ]
    assert received == {
        "settings": application.state.settings,
        "pool": database_pool,
        "cache": application.state.caches.competitions,
    }


def test_sitemap_is_valid_xml_without_fake_metadata_or_technical_routes(monkeypatch):
    install_public_data(monkeypatch)
    application = main.create_app(production_settings())
    response = asyncio.run(main.sitemap(request_for(application, "/sitemap.xml")))
    root = ElementTree.fromstring(response.body)
    body = response.body.decode()
    assert root.tag == "{http://www.sitemaps.org/schemas/sitemap/0.9}urlset"
    assert all(url.startswith(CANONICAL_BASE_URL) for url in sitemap_locations(response))
    assert "up.railway.app" not in body
    assert "/health" not in body
    assert "/docs" not in body
    assert "/redoc" not in body
    assert "/openapi.json" not in body
    assert "lastmod" not in body
    assert "priority" not in body
    assert "changefreq" not in body


def test_sitemap_database_failure_and_empty_list_keep_static_pages(monkeypatch):
    application = main.create_app(production_settings())

    async def unavailable(*args, **kwargs):
        raise DatabaseUnavailableError("private database detail")

    monkeypatch.setattr(main, "get_competitions", unavailable)
    failed = asyncio.run(main.sitemap(request_for(application, "/sitemap.xml")))
    assert sitemap_locations(failed) == [
        f"{CANONICAL_BASE_URL}/",
        f"{CANONICAL_BASE_URL}/competitions",
        f"{CANONICAL_BASE_URL}/faq",
    ]
    assert b"private database detail" not in failed.body

    async def empty(*args, **kwargs):
        return []

    monkeypatch.setattr(main, "get_competitions", empty)
    empty_response = asyncio.run(
        main.sitemap(request_for(application, "/sitemap.xml"))
    )
    assert sitemap_locations(empty_response) == sitemap_locations(failed)


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
    response = asyncio.run(main.sitemap(request_for(application, "/sitemap.xml")))
    assert sitemap_locations(response) == []
    assert b"localhost" not in response.body


def test_every_sitemap_url_has_matching_canonical(monkeypatch):
    install_public_data(monkeypatch)
    application = main.create_app(production_settings())
    sitemap_response = asyncio.run(
        main.sitemap(request_for(application, "/sitemap.xml"))
    )
    for location in sitemap_locations(sitemap_response):
        path = location.removeprefix(CANONICAL_BASE_URL)
        status, _, body = html_response(application, path)
        assert status == 200
        assert canonical_url(body) == location


@pytest.mark.parametrize("path", ["/health", "/health/db"])
def test_health_endpoints_use_x_robots_tag(path):
    status, headers, _ = asgi_get(main.create_app(production_settings()), path)
    assert status in {200, 503}
    assert headers["x-robots-tag"] == "noindex, nofollow"


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_production_documentation_routes_are_absent_and_noindex(path):
    status, _, body = html_response(
        main.create_app(production_settings(docs=True)),
        path,
    )
    assert status == 404
    assert meta_content(body, name="robots") == "noindex, nofollow"
    assert canonical_url(body) is None


def test_empty_competition_list_keeps_indexable_metadata_and_one_h1(monkeypatch):
    install_public_data(monkeypatch, competitions=[])
    application = main.create_app(production_settings())
    for path in ("/", "/competitions"):
        status, _, body = html_response(application, path)
        assert status == 200
        assert meta_content(body, name="robots") == "index, follow"
        assert canonical_url(body) == f"{CANONICAL_BASE_URL}{path}"
        assert len(re.findall(r"<h1(?:\s|>)", body)) == 1


def test_competition_cards_use_crawlable_href_links(monkeypatch):
    install_public_data(monkeypatch)
    _, _, body = html_response(
        main.create_app(production_settings()),
        "/competitions",
    )
    assert 'href="https://testserver/competitions/7"' in body
    assert "onclick=" not in body


def test_rendered_html_and_sitemap_do_not_contain_old_railway_domain(monkeypatch):
    install_public_data(monkeypatch)
    application = main.create_app(production_settings())
    documents = [
        html_response(application, path)[2]
        for path in ("/", "/competitions", "/competitions/7", "/faq")
    ]
    documents.append(
        asyncio.run(main.sitemap(request_for(application, "/sitemap.xml"))).body.decode()
    )
    assert all("up.railway.app" not in document for document in documents)
    assert all("artflow.example.test" not in document for document in documents)


def test_service_seo_source_contains_actual_values_without_display_fallbacks():
    from app.services.competitions import _serialize_competition

    serialized = _serialize_competition(
        {
            "id": 7,
            "name": "Реальное название",
            "short_description": None,
            "description": "Реальное описание",
            "event_date": "2026-09-05",
            "application_deadline": None,
            "city": None,
            "place": "Реальная сцена",
            "is_published": True,
        },
        production_settings(),
    )
    assert serialized["is_published"] is True
    assert serialized["seo_source"] == {
        "name": "Реальное название",
        "description": "Реальное описание",
        "event_date": "2026-09-05",
        "city": None,
        "place": "Реальная сцена",
    }
