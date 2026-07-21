from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime
from typing import Any
from urllib.parse import urlsplit

from app.cache import AsyncTTLCache
from app.config import Settings, normalize_bot_username, settings
from app.repositories import competitions as competitions_repository


Competition = dict[str, Any]

_DIRECTIONS_SEPARATOR = re.compile(r"[,;\r\n]+")
_DEFAULT_SHORT_DESCRIPTION = "Краткая информация о конкурсе скоро появится."
_DEFAULT_DESCRIPTION = "Подробная информация о конкурсе скоро появится."
_PUBLIC_CACHE_TTL_SECONDS = 30

_competitions_cache: AsyncTTLCache[tuple[Any, ...], list[Competition]] = AsyncTTLCache(
    ttl_seconds=_PUBLIC_CACHE_TTL_SECONDS,
    max_entries=8,
)
_competition_detail_cache: AsyncTTLCache[
    tuple[Any, ...], Competition | None
] = AsyncTTLCache(
    ttl_seconds=_PUBLIC_CACHE_TTL_SECONDS,
    max_entries=64,
)


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
    if active_settings.is_production and scheme != "https":
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
) -> Competition:
    name = _text(row.get("name")) or "Конкурс ArtFlow"
    raw_short_description = _text(row.get("short_description"))
    raw_description = _text(row.get("description"))
    short_description = raw_short_description or _DEFAULT_SHORT_DESCRIPTION
    description = raw_description or _DEFAULT_DESCRIPTION

    event_date = _format_date(row.get("event_date")) or "Дата уточняется"
    deadline_value = _date_value(row.get("application_deadline"))
    application_deadline = (
        _format_date(deadline_value) if deadline_value else "Срок уточняется"
    )

    return {
        "id": row.get("id"),
        "name": name,
        "short_description": short_description,
        "description": description,
        "event_date": event_date,
        "application_deadline": application_deadline,
        "city": _text(row.get("city")) or "Город уточняется",
        "place": _text(row.get("place")) or "Место уточняется",
        "directions": _directions(row.get("directions")),
        "poster_url": _http_url(row.get("poster_url"), app_settings),
        "rules_url": _http_url(row.get("rules_url"), app_settings),
        "price": _text(row.get("price")) or "Стоимость уточняется",
        "registration_is_open": (
            deadline_value is not None and date.today() <= deadline_value
        ),
        "telegram_url": _telegram_url(row.get("id"), app_settings),
    }


def _settings_cache_key(app_settings: Settings) -> tuple[bool, str | None]:
    return (app_settings.is_production, app_settings.bot_username)


async def get_competitions(
    app_settings: Settings | None = None,
) -> list[Competition]:
    active_settings = app_settings or settings

    async def load() -> list[Competition]:
        rows = await competitions_repository.get_published_competitions()
        return [_serialize_competition(row, active_settings) for row in rows]

    cache_key = ("all", *_settings_cache_key(active_settings))
    return await _competitions_cache.get_or_load(cache_key, load)


async def get_featured_competitions(
    limit: int = 3,
    app_settings: Settings | None = None,
) -> list[Competition]:
    active_settings = app_settings or settings
    safe_limit = max(1, min(limit, 12))

    async def load() -> list[Competition]:
        rows = await competitions_repository.get_published_competitions(
            limit=safe_limit
        )
        return [_serialize_competition(row, active_settings) for row in rows]

    cache_key = (
        "featured",
        safe_limit,
        *_settings_cache_key(active_settings),
    )
    return await _competitions_cache.get_or_load(cache_key, load)


async def get_competition_by_id(
    competition_id: int,
    app_settings: Settings | None = None,
) -> Competition | None:
    active_settings = app_settings or settings

    async def load() -> Competition | None:
        row = await competitions_repository.get_published_competition_by_id(
            competition_id
        )
        return (
            _serialize_competition(row, active_settings)
            if row is not None
            else None
        )

    cache_key = (competition_id, *_settings_cache_key(active_settings))
    return await _competition_detail_cache.get_or_load(cache_key, load)


def clear_competition_cache() -> None:
    _competitions_cache.clear()
    _competition_detail_cache.clear()
