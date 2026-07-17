from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any
from urllib.parse import urlsplit

from app.config import normalize_bot_username, settings
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


def _http_url(value: Any) -> str | None:
    url = _text(value)
    if url is None or any(ord(character) < 32 for character in url):
        return None

    try:
        parsed = urlsplit(url)
        hostname = parsed.hostname
    except ValueError:
        return None

    if parsed.scheme.lower() not in {"http", "https"} or hostname is None:
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


def _telegram_url(competition_id: Any) -> str | None:
    return build_competition_telegram_url(
        settings.bot_username,
        competition_id,
    )


def _serialize_competition(row: Competition) -> Competition:
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
        "poster_url": _http_url(row.get("poster_url")),
        "rules_url": _http_url(row.get("rules_url")),
        "price": _text(row.get("price")) or "Стоимость уточняется",
        "registration_is_open": (
            deadline_value is not None and date.today() <= deadline_value
        ),
        "telegram_url": _telegram_url(row.get("id")),
    }


async def get_competitions() -> list[Competition]:
    rows = await competitions_repository.get_published_competitions()
    return [_serialize_competition(row) for row in rows]


async def get_featured_competitions(limit: int = 3) -> list[Competition]:
    rows = await competitions_repository.get_published_competitions(limit=limit)
    return [_serialize_competition(row) for row in rows]


async def get_competition_by_id(competition_id: int) -> Competition | None:
    row = await competitions_repository.get_published_competition_by_id(
        competition_id
    )
    return _serialize_competition(row) if row is not None else None
