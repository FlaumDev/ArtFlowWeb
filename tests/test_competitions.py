import asyncio
import re
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import database
from app.cache import ApplicationCaches
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
        "application_deadline": date(2026, 9, 1),
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
    assert 'decoding="async"' in card
    assert 'decoding="async"' in detail
    assert "Афиша конкурса {{ competition.name }}" in card
    assert "Афиша конкурса {{ competition.name }}" in detail
    assert "poster-frame" in card and "poster-frame" in detail
    assert "data-poster-image" in card and "data-poster-placeholder" in card
    assert "data-poster-image" in detail and "data-poster-placeholder" in detail
    poster_tags = [
        re.search(r"<img[^>]+data-poster-image[^>]*>", template, re.DOTALL).group(0)
        for template in (card, detail)
    ]
    assert all("hidden" not in poster_tag for poster_tag in poster_tags)
    assert 'addEventListener("load"' in javascript
    assert 'addEventListener("error"' in javascript
    assert 'image.removeAttribute("hidden")' in javascript
    assert "image.hidden" not in javascript
    assert "placeholder.hidden = false" in javascript


def test_missing_poster_url_stays_missing():
    result = competitions_service._serialize_competition(
        competition_row(poster_url=None)
    )

    assert result["poster_url"] is None


def test_https_poster_url_is_passed_to_template_data():
    poster_url = "https://cdn.example.test/posters/artflow"

    result = competitions_service._serialize_competition(
        competition_row(poster_url=poster_url)
    )

    assert result["poster_url"] == poster_url


def test_html_poster_url_relies_only_on_client_fallback():
    result = competitions_service._serialize_competition(
        competition_row(poster_url="https://www.google.com")
    )
    javascript = (PROJECT_ROOT / "static/js/main.js").read_text(encoding="utf-8")
    backend_source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (PROJECT_ROOT / "app").rglob("*.py")
    ).lower()

    assert result["poster_url"] == "https://www.google.com"
    assert 'addEventListener("error", showPlaceholder' in javascript
    assert not {"requests", "httpx", "aiohttp"}.intersection(
        set(re.findall(r"[a-z_]+", backend_source))
    )


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


def test_competition_fields_are_not_moved_between_contract_fields():
    result = competitions_service._serialize_competition(
        competition_row(
            date="Старое значение даты",
            event_date=None,
            city=None,
            place="Краткое описание",
            short_description=None,
            description="Полное описание",
        )
    )

    assert result["event_date"] == "Дата уточняется"
    assert result["city"] == "Город уточняется"
    assert result["place"] == "Краткое описание"
    assert result["short_description"] == (
        "Краткая информация о конкурсе скоро появится."
    )
    assert result["description"] == "Полное описание"


def test_registration_deadline_is_inclusive():
    fixed_now = datetime(2026, 9, 1, 12, tzinfo=timezone.utc)
    deadline = date(2026, 9, 1)
    open_result = competitions_service._serialize_competition(
        competition_row(application_deadline=deadline),
        now=fixed_now,
    )
    closed_result = competitions_service._serialize_competition(
        competition_row(application_deadline=date(2026, 8, 31)),
        now=fixed_now,
    )
    missing_result = competitions_service._serialize_competition(
        competition_row(application_deadline=None),
        now=fixed_now,
    )

    assert open_result["registration_is_open"] is True
    assert closed_result["registration_is_open"] is False
    assert missing_result["registration_is_open"] is False


def test_negative_competition_id_skips_database(monkeypatch):
    def fail_if_called(_pool):
        raise AssertionError("Database must not be queried for a negative ID")

    monkeypatch.setattr(
        competitions_repository,
        "get_connection",
        fail_if_called,
    )
    result = asyncio.run(
        competitions_repository.get_published_competition_by_id(
            -1,
            pool=None,
        )
    )
    assert result is None


def test_repository_queries_are_select_only():
    queries = (
        competitions_repository._PUBLISHED_COMPETITIONS_SQL,
        competitions_repository._PUBLISHED_COMPETITIONS_WITH_LIMIT_SQL,
        competitions_repository._RELATED_COMPETITIONS_SQL,
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
    related_query = " ".join(
        competitions_repository._RELATED_COMPETITIONS_SQL.upper().split()
    )
    assert "ID <> %S" in related_query
    assert "LIMIT %S" in related_query
    assert "ID = %S" in " ".join(
        competitions_repository._PUBLISHED_COMPETITION_BY_ID_SQL.upper().split()
    )


def test_pool_has_small_bounded_configuration():
    assert database.POOL_MIN_SIZE == 1
    assert database.POOL_MAX_SIZE == 5
    assert database.POOL_ACQUIRE_TIMEOUT_SECONDS <= 5


def test_missing_pool_returns_controlled_error(monkeypatch):
    async def acquire():
        async with database.get_connection(None):
            raise AssertionError("No connection should be yielded")

    with pytest.raises(database.DatabaseUnavailableError):
        asyncio.run(acquire())

def test_related_competitions_are_bounded_deduplicated_published_and_cached(
    monkeypatch,
):
    calls = []

    async def related_rows(
        competition_id,
        *,
        city,
        reference_date,
        limit,
        pool,
    ):
        calls.append(
            {
                "competition_id": competition_id,
                "city": city,
                "reference_date": reference_date,
                "limit": limit,
                "pool": pool,
            }
        )
        return [
            competition_row(id=8, name="Same city"),
            competition_row(id=7, name="Current"),
            competition_row(id=9, name="Unpublished", is_published=False),
            competition_row(id=8, name="Duplicate"),
            competition_row(id=10, name="Another"),
            competition_row(id=11, name="Beyond limit"),
        ]

    monkeypatch.setattr(
        competitions_repository,
        "get_related_published_competitions",
        related_rows,
    )
    pool = object()
    cache = ApplicationCaches().competitions
    fixed_now = datetime(2026, 9, 1, 20, 30, tzinfo=timezone.utc)

    first = asyncio.run(
        competitions_service.get_related_competitions(
            7,
            "Алматы",
            limit=8,
            database_pool=pool,
            cache=cache,
            now=fixed_now,
        )
    )
    second = asyncio.run(
        competitions_service.get_related_competitions(
            7,
            "Алматы",
            limit=8,
            database_pool=pool,
            cache=cache,
            now=fixed_now,
        )
    )

    assert [item["id"] for item in first] == [8, 10, 11]
    assert second == first
    assert len(calls) == 1
    assert calls[0]["competition_id"] == 7
    assert calls[0]["city"] == "Алматы"
    assert calls[0]["limit"] == 3
    assert calls[0]["pool"] is pool


@pytest.mark.parametrize(("competition_id", "limit"), [(0, 3), (-1, 3), (7, 0)])
def test_invalid_related_competition_request_skips_repository(
    monkeypatch,
    competition_id,
    limit,
):
    async def must_not_load(*args, **kwargs):
        raise AssertionError("Repository must not be called")

    monkeypatch.setattr(
        competitions_repository,
        "get_related_published_competitions",
        must_not_load,
    )
    assert asyncio.run(
        competitions_service.get_related_competitions(
            competition_id,
            "Алматы",
            limit=limit,
        )
    ) == []
