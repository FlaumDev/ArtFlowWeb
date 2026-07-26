from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime, timezone
from typing import Any
from urllib.parse import urlsplit

from app.cache import AsyncTTLCache
from app.clock import current_date
from app.config import (
    Settings,
    is_public_hostname,
    normalize_bot_username,
    settings,
)
from app.database import DatabasePool
from app.repositories import competitions as competitions_repository


Competition = dict[str, Any]

_DIRECTIONS_SEPARATOR = re.compile(r"[,;\r\n]+")
_DEFAULT_SHORT_DESCRIPTION = "Краткая информация о конкурсе скоро появится."
_DEFAULT_DESCRIPTION = "Подробная информация о конкурсе скоро появится."


def _text(value: Any) -> str | None:
    if value is None:
        return None

    normalized = str(value).strip()
    return normalized or None


def _date_value(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip())
        except ValueError:
            return None
    return None


def _format_date(value: Any) -> str | None:
    normalized = _date_value(value)
    if normalized is None:
        return None
    return normalized.strftime("%d.%m.%Y")


def _directions(value: Any) -> list[str]:
    text = _text(value)
    if text is None:
        return []

    result: list[str] = []
    seen: set[str] = set()

    for item in _DIRECTIONS_SEPARATOR.split(text):
        direction = item.strip()
        key = direction.casefold()
        if not direction or key in seen:
            continue
        seen.add(key)
        result.append(direction)

    return result


def _http_url(
    value: Any,
    app_settings: Settings | None = None,
) -> str | None:
    if isinstance(value, str) and any(
        unicodedata.category(character) == "Cc" for character in value
    ):
        return None

    url = _text(value)
    if url is None:
        return None

    try:
        parsed = urlsplit(url)
        hostname = parsed.hostname
        parsed.port
    except ValueError:
        return None

    scheme = parsed.scheme.lower()
    if (
        scheme not in {"http", "https"}
        or hostname is None
        or parsed.username is not None
        or parsed.password is not None
    ):
        return None
    active_settings = app_settings or settings
    if active_settings.is_production:
        if scheme != "https" or not is_public_hostname(hostname):
            return None

    return url


def build_competition_telegram_url(
    bot_username: str | None,
    competition_id: Any,
) -> str | None:
    username = normalize_bot_username(bot_username)
    if username is None or type(competition_id) is not int or competition_id <= 0:
        return None

    return f"https://t.me/{username}?start=competition_{competition_id}"


def _telegram_url(
    competition_id: Any,
    app_settings: Settings | None = None,
) -> str | None:
    active_settings = app_settings or settings
    return build_competition_telegram_url(
        active_settings.bot_username,
        competition_id,
    )


def _serialize_competition(
    row: Competition,
    app_settings: Settings | None = None,
    *,
    now: datetime | None = None,
) -> Competition:
    active_settings = app_settings or settings
    name = _text(row.get("name")) or "Конкурс ArtFlow"
    raw_short_description = _text(row.get("short_description"))
    raw_description = _text(row.get("description"))
    short_description = raw_short_description or _DEFAULT_SHORT_DESCRIPTION
    description = raw_description or _DEFAULT_DESCRIPTION

    event_date_value = _date_value(row.get("event_date"))
    event_date = _format_date(event_date_value) or "Дата уточняется"
    deadline_value = _date_value(row.get("application_deadline"))
    application_deadline = (
        _format_date(deadline_value) if deadline_value else "Срок уточняется"
    )

    city = _text(row.get("city"))
    place = _text(row.get("place"))
    return {
        "id": row.get("id"),
        "name": name,
        "short_description": short_description,
        "description": description,
        "event_date": event_date,
        "application_deadline": application_deadline,
        "city": city or "Город уточняется",
        "place": place or "Место уточняется",
        "directions": _directions(row.get("directions")),
        "poster_url": _http_url(row.get("poster_url"), active_settings),
        "rules_url": _http_url(row.get("rules_url"), active_settings),
        "price": _text(row.get("price")) or "Стоимость уточняется",
        "registration_is_open": (
            deadline_value is not None
            and current_date(active_settings, now=now) <= deadline_value
        ),
        "telegram_url": _telegram_url(row.get("id"), active_settings),
        "is_published": row.get("is_published") is True,
        "seo_source": {
            "name": _text(row.get("name")),
            "description": raw_short_description or raw_description,
            "event_date": (
                event_date_value.isoformat() if event_date_value else None
            ),
            "city": city,
            "place": place,
        },
    }


async def get_competitions(
    app_settings: Settings | None = None,
    *,
    database_pool: DatabasePool | None = None,
    cache: AsyncTTLCache[tuple[Any, ...], list[Competition]] | None = None,
    now: datetime | None = None,
) -> list[Competition]:
    active_settings = app_settings or settings

    async def load() -> list[Competition]:
        rows = await competitions_repository.get_published_competitions(
            pool=database_pool
        )
        serialized_at = now or datetime.now(timezone.utc)
        return [
            _serialize_competition(
                row,
                active_settings,
                now=serialized_at,
            )
            for row in rows
        ]

    if cache is None:
        return await load()
    return await cache.get_or_load(("all",), load)


async def get_featured_competitions(
    limit: int = 3,
    app_settings: Settings | None = None,
    *,
    database_pool: DatabasePool | None = None,
    cache: AsyncTTLCache[tuple[Any, ...], list[Competition]] | None = None,
    now: datetime | None = None,
) -> list[Competition]:
    active_settings = app_settings or settings
    safe_limit = max(1, min(limit, 12))

    async def load() -> list[Competition]:
        rows = await competitions_repository.get_published_competitions(
            limit=safe_limit,
            pool=database_pool,
        )
        serialized_at = now or datetime.now(timezone.utc)
        return [
            _serialize_competition(
                row,
                active_settings,
                now=serialized_at,
            )
            for row in rows
        ]

    if cache is None:
        return await load()
    return await cache.get_or_load(("featured", safe_limit), load)


async def get_competition_by_id(
    competition_id: int,
    app_settings: Settings | None = None,
    *,
    database_pool: DatabasePool | None = None,
    cache: AsyncTTLCache[int, Competition | None] | None = None,
    now: datetime | None = None,
) -> Competition | None:
    active_settings = app_settings or settings

    async def load() -> Competition | None:
        row = await competitions_repository.get_published_competition_by_id(
            competition_id,
            pool=database_pool,
        )
        return (
            _serialize_competition(
                row,
                active_settings,
                now=now or datetime.now(timezone.utc),
            )
            if row is not None
            else None
        )

    if cache is None:
        return await load()
    return await cache.get_or_load(competition_id, load)
