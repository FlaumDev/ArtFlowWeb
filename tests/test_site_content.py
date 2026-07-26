import asyncio
import json
from pathlib import Path

import pytest
from fastapi import HTTPException, Request

from app import main
from app.repositories import competitions as competitions_repository
from app.routers import competitions as competition_routes
from app.routers import faq as faq_routes
from app.site_content import get_site_content, load_site_content


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def sample_competition():
    return {
        "id": 7,
        "name": "ArtFlow Test",
        "short_description": "Творческий конкурс для юных артистов.",
        "description": "Подробное описание события ArtFlow.",
        "event_date": "05.09.2026",
        "application_deadline": "01.09.2026",
        "city": "Алматы",
        "place": "Городская сцена",
        "directions": ["Вокал", "Хореография"],
        "poster_url": None,
        "rules_url": "https://example.test/rules",
        "price": "12 000 ₸",
        "registration_is_open": True,
        "telegram_url": "https://t.me/ArtFlowBot?start=competition_7",
    }


def install_route_fakes(monkeypatch, site_content=None):
    competition = sample_competition()
    content = site_content or get_site_content()

    async def featured_competitions(
        limit=3,
        app_settings=None,
        database_pool=None,
        cache=None,
    ):
        return [competition][:limit]

    async def all_competitions(
        app_settings=None,
        database_pool=None,
        cache=None,
    ):
        return [competition]

    async def one_competition(
        competition_id,
        app_settings=None,
        database_pool=None,
        cache=None,
    ):
        return competition if competition_id == competition["id"] else None

    async def faq_items(database_pool=None, cache=None):
        return [{"id": 1, "question": "Как участвовать?", "answer": "Выберите конкурс."}]

    monkeypatch.setattr(main, "get_featured_competitions", featured_competitions)
    monkeypatch.setattr(main, "get_faq_items", faq_items)
    monkeypatch.setattr(main, "get_site_content", lambda: content)
    monkeypatch.setattr(competition_routes, "get_competitions", all_competitions)
    monkeypatch.setattr(competition_routes, "get_competition_by_id", one_competition)
    monkeypatch.setattr(competition_routes, "get_site_content", lambda: content)
    monkeypatch.setattr(faq_routes, "get_faq_items", faq_items)
    monkeypatch.setattr(faq_routes, "get_site_content", lambda: content)


def request_for(path):
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": [],
            "client": ("test", 50000),
            "server": ("testserver", 80),
            "root_path": "",
            "app": main.app,
        }
    )


def write_content(tmp_path, content):
    content_path = tmp_path / "site_content.json"
    content_path.write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")
    return content_path


def test_site_content_json_loads_public_content():
    content = get_site_content()

    assert content["brand"]["name"] == "ArtFlow"
    assert content["contacts"]["email"] == "lemani1974@mail.ru"
    assert [item["name"] for item in content["contacts"]["organizers"]] == [
        "Елена",
        "Марина",
    ]
    assert len(content["gallery"]) == 6


def test_missing_site_content_file_returns_safe_defaults(tmp_path):
    content = load_site_content(tmp_path / "missing.json")

    assert content["brand"]["name"] == "ArtFlow"
    assert content["contacts"]["organizers"] == []
    assert content["gallery"] == []
    assert content["has_contacts"] is False


def test_empty_and_placeholder_contact_links_are_removed(tmp_path):
    path = write_content(
        tmp_path,
        {
            "contacts": {
                "email": "CHANGE_ME",
                "instagram": {"label": "profile", "url": "ВСТАВЬ_URL"},
                "organizers": [
                    {
                        "name": "Организатор",
                        "whatsapp_url": "#",
                        "telegram_url": "TELEGRAM_1",
                    }
                ],
            }
        },
    )

    content = load_site_content(path)

    assert content["contacts"]["email"] == ""
    assert content["contacts"]["instagram"]["url"] == ""
    assert content["contacts"]["organizers"][0]["whatsapp_url"] == ""
    assert content["contacts"]["organizers"][0]["telegram_url"] == ""
    assert content["has_contacts"] is False


def test_bot_deep_link_is_not_replaced_by_organizer_contacts():
    content = get_site_content()
    detail_template = (PROJECT_ROOT / "templates/competition_detail.html").read_text(
        encoding="utf-8"
    )

    assert 'href="{{ competition.telegram_url }}"' in detail_template
    assert all(
        organizer["telegram_url"] != "https://t.me/ArtFlowBot?start=competition_7"
        for organizer in content["contacts"]["organizers"]
    )


def test_organizer_whatsapp_and_telegram_are_separate_links():
    organizers = get_site_content()["contacts"]["organizers"]

    assert all(item["whatsapp_url"].startswith("https://wa.me/") for item in organizers)
    assert all(item["telegram_url"].startswith("https://t.me/") for item in organizers)
    assert all(item["whatsapp_url"] != item["telegram_url"] for item in organizers)


def test_missing_gallery_files_are_excluded(tmp_path):
    missing_src = "/static/images/gallery-does-not-exist.webp"
    path = write_content(
        tmp_path,
        {
            "gallery": [
                {"src": missing_src, "alt": "Отсутствующая фотография"}
            ],
            "sections": {"gallery_enabled": True},
        },
    )

    content = load_site_content(path)

    assert content["gallery"] == []
    assert missing_src not in json.dumps(content, ensure_ascii=False)


def test_instagram_section_is_hidden_when_url_is_blank(tmp_path, monkeypatch):
    path = write_content(
        tmp_path,
        {
            "contacts": {"instagram": {"label": "artflow", "url": ""}},
            "sections": {"instagram_enabled": True},
        },
    )
    content = load_site_content(path)
    install_route_fakes(monkeypatch, content)

    response = asyncio.run(main.index(request_for("/")))

    assert response.status_code == 200
    assert 'class="instagram-section"' not in response.body.decode()


def test_site_contacts_do_not_change_competition_sql():
    source = (PROJECT_ROOT / "app/site_content.py").read_text(encoding="utf-8")
    queries = (
        competitions_repository._PUBLISHED_COMPETITIONS_SQL,
        competitions_repository._PUBLISHED_COMPETITIONS_WITH_LIMIT_SQL,
        competitions_repository._PUBLISHED_COMPETITION_BY_ID_SQL,
    )

    assert "app.database" not in source
    assert "app.repositories" not in source
    assert all(" ".join(query.upper().split()).startswith("SELECT ") for query in queries)


def test_public_routes_keep_working_without_real_database(monkeypatch):
    install_route_fakes(monkeypatch)

    assert asyncio.run(main.index(request_for("/"))).status_code == 200
    assert asyncio.run(
        competition_routes.competitions(request_for("/competitions"))
    ).status_code == 200
    assert asyncio.run(
        competition_routes.competition_detail(
            request_for("/competitions/7"), 7
        )
    ).status_code == 200
    with pytest.raises(HTTPException) as error:
        asyncio.run(
            competition_routes.competition_detail(
                request_for("/competitions/999999"), 999999
            )
        )
    assert error.value.status_code == 404
    assert asyncio.run(faq_routes.faq(request_for("/faq"))).status_code == 200
    health_response = asyncio.run(main.health())
    assert health_response.status_code == 200
    assert health_response.body == b'{"status":"ok"}'


def test_detail_page_keeps_deep_link_and_separate_help_contacts(monkeypatch):
    install_route_fakes(monkeypatch)

    response = asyncio.run(
        competition_routes.competition_detail(request_for("/competitions/7"), 7)
    )
    response_text = response.body.decode()

    assert response.status_code == 200
    assert "https://t.me/ArtFlowBot?start=competition_7" in response_text
    assert "https://wa.me/77052510210" in response_text
    assert "https://t.me/elenaflaum" in response_text
