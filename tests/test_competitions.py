import asyncio
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import database
from app.config import normalize_bot_username
from app.repositories import competitions as competitions_repository
from app.services import competitions as competitions_service


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def competition_row(**overrides):
    row = {
        "id": 7,
        "name": "ArtFlow Test",
        "description": "Описание конкурса",
        "date": None,
        "place": "Площадка",
        "price": "2500 рублей",
        "event_date": date(2026, 9, 5),
        "application_deadline": date.today(),
        "city": "Москва",
        "short_description": "Краткое описание",
        "directions": "Вокал, Хореография",
        "poster_url": None,
        "rules_url": None,
        "is_published": True,
        "updated_at": None,
    }
    row.update(overrides)
    return row


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("ArtFlowBot", "ArtFlowBot"),
        ("@ArtFlowBot", "ArtFlowBot"),
        (None, None),
        ("", None),
        ("https://t.me/ArtFlowBot", None),
    ],
)
def test_normalize_bot_username(value, expected):
    assert normalize_bot_username(value) == expected


@pytest.mark.parametrize("username", ["ArtFlowBot", "@ArtFlowBot"])
def test_competition_deep_link(username):
    assert competitions_service.build_competition_telegram_url(
        username,
        7,
    ) == "https://t.me/ArtFlowBot?start=competition_7"


@pytest.mark.parametrize("competition_id", [0, -1, True, 1.5, "7"])
def test_competition_deep_link_rejects_invalid_id(competition_id):
    assert (
        competitions_service.build_competition_telegram_url(
            "ArtFlowBot",
            competition_id,
        )
        is None
    )


def test_competition_deep_link_requires_username():
    assert competitions_service.build_competition_telegram_url(None, 7) is None


def test_service_deep_link_uses_settings(monkeypatch):
    monkeypatch.setattr(
        competitions_service,
        "settings",
        SimpleNamespace(bot_username="@ArtFlowBot"),
    )
    assert (
        competitions_service._telegram_url(7)
        == "https://t.me/ArtFlowBot?start=competition_7"
    )


def test_directions_are_split_trimmed_and_deduplicated():
    assert competitions_service._directions(
        "Вокал, Хореография; вокал\nТеатр\r\n"
    ) == ["Вокал", "Хореография", "Театр"]
    assert competitions_service._directions(None) == []


def test_dates_are_formatted_for_visitors():
    assert competitions_service._format_date(date(2026, 9, 5)) == "05.09.2026"
    assert (
        competitions_service._format_date(datetime(2026, 9, 5, 12, 30))
        == "05.09.2026"
    )
    assert competitions_service._format_date(None) is None


def test_invalid_urls_are_removed_without_external_request():
    assert competitions_service._http_url("javascript:alert(1)") is None
    assert competitions_service._http_url("data:image/png;base64,abc") is None
    assert competitions_service._http_url("C:/poster.jpg") is None
    assert competitions_service._http_url("https://www.google.com") == (
        "https://www.google.com"
    )


def test_poster_templates_and_browser_fallback_contract():
    card = (PROJECT_ROOT / "templates/components/competition_card.html").read_text(
        encoding="utf-8"
    )
    detail = (PROJECT_ROOT / "templates/competition_detail.html").read_text(
        encoding="utf-8"
    )
    javascript = (PROJECT_ROOT / "static/js/main.js").read_text(encoding="utf-8")

    assert 'loading="lazy"' in card
    assert 'loading="eager"' in detail
    assert "data-poster-image" in card and "data-poster-placeholder" in card
    assert "data-poster-image" in detail and "data-poster-placeholder" in detail
    assert 'addEventListener("load"' in javascript
    assert 'addEventListener("error"' in javascript
    assert "image.hidden = true" in javascript
    assert "placeholder.hidden = false" in javascript


def test_nullable_fields_have_safe_fallbacks(monkeypatch):
    monkeypatch.setattr(
        competitions_service,
        "settings",
        SimpleNamespace(bot_username=None),
    )
    result = competitions_service._serialize_competition(
        competition_row(
            name=None,
            description=None,
            short_description=None,
            event_date=None,
            application_deadline=None,
            city=None,
            place=None,
            directions=None,
            price=None,
        )
    )

    assert result["name"] == "Конкурс ArtFlow"
    assert result["event_date"] == "Дата уточняется"
    assert result["application_deadline"] == "Срок уточняется"
    assert result["city"] == "Город уточняется"
    assert result["place"] == "Место уточняется"
    assert result["directions"] == []
    assert result["registration_is_open"] is False
    assert result["telegram_url"] is None


def test_registration_deadline_is_inclusive():
    today = date.today()
    open_result = competitions_service._serialize_competition(
        competition_row(application_deadline=today)
    )
    closed_result = competitions_service._serialize_competition(
        competition_row(application_deadline=today - timedelta(days=1))
    )
    missing_result = competitions_service._serialize_competition(
        competition_row(application_deadline=None)
    )

    assert open_result["registration_is_open"] is True
    assert closed_result["registration_is_open"] is False
    assert missing_result["registration_is_open"] is False


def test_negative_competition_id_skips_database(monkeypatch):
    def fail_if_called():
        raise AssertionError("Database must not be queried for a negative ID")

    monkeypatch.setattr(
        competitions_repository,
        "get_connection",
        fail_if_called,
    )
    result = asyncio.run(
        competitions_repository.get_published_competition_by_id(-1)
    )
    assert result is None


def test_repository_queries_are_select_only():
    queries = (
        competitions_repository._PUBLISHED_COMPETITIONS_SQL,
        competitions_repository._PUBLISHED_COMPETITIONS_WITH_LIMIT_SQL,
        competitions_repository._PUBLISHED_COMPETITION_BY_ID_SQL,
    )
    forbidden = {"INSERT", "UPDATE", "DELETE", "CREATE", "ALTER", "DROP", "TRUNCATE"}

    for query in queries:
        normalized = " ".join(query.upper().split())
        tokens = set(re.findall(r"[A-Z_]+", normalized))
        assert normalized.startswith("SELECT ")
        assert "SELECT *" not in normalized
        assert "FROM COMPETITIONS" in normalized
        assert not forbidden.intersection(tokens)

    assert "LIMIT %S" in " ".join(
        competitions_repository._PUBLISHED_COMPETITIONS_WITH_LIMIT_SQL.upper().split()
    )
    assert "ID = %S" in " ".join(
        competitions_repository._PUBLISHED_COMPETITION_BY_ID_SQL.upper().split()
    )


def test_pool_has_small_bounded_configuration():
    assert database.POOL_MIN_SIZE == 1
    assert database.POOL_MAX_SIZE == 5
    assert database.POOL_ACQUIRE_TIMEOUT_SECONDS <= 5


def test_missing_pool_returns_controlled_error(monkeypatch):
    monkeypatch.setattr(database, "_pool", None)

    async def acquire():
        async with database.get_connection():
            raise AssertionError("No connection should be yielded")

    with pytest.raises(database.DatabaseUnavailableError):
        asyncio.run(acquire())
