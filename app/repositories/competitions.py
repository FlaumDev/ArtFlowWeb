from __future__ import annotations

from datetime import date
from typing import Any

from app.database import DatabasePool, get_connection


CompetitionRow = dict[str, Any]

_PUBLISHED_COMPETITIONS_SQL = """
    SELECT
        id,
        name,
        description,
        place,
        price,
        event_date,
        application_deadline,
        city,
        short_description,
        directions,
        poster_url,
        rules_url,
        is_published,
        updated_at
    FROM competitions
    WHERE is_published = TRUE
    ORDER BY event_date ASC NULLS LAST, id ASC
"""

_PUBLISHED_COMPETITIONS_WITH_LIMIT_SQL = """
    SELECT
        id,
        name,
        description,
        place,
        price,
        event_date,
        application_deadline,
        city,
        short_description,
        directions,
        poster_url,
        rules_url,
        is_published,
        updated_at
    FROM competitions
    WHERE is_published = TRUE
    ORDER BY event_date ASC NULLS LAST, id ASC
    LIMIT %s
"""

_RELATED_COMPETITIONS_SQL = """
    SELECT
        id,
        name,
        description,
        place,
        price,
        event_date,
        application_deadline,
        city,
        short_description,
        directions,
        poster_url,
        rules_url,
        is_published,
        updated_at
    FROM competitions
    WHERE is_published = TRUE AND id <> %s
    ORDER BY
        CASE
            WHEN LOWER(BTRIM(city)) = LOWER(BTRIM(%s)) THEN 0
            ELSE 1
        END,
        CASE WHEN event_date >= %s THEN 0 ELSE 1 END,
        CASE WHEN event_date >= %s THEN event_date END ASC NULLS LAST,
        event_date DESC NULLS LAST,
        id ASC
    LIMIT %s
"""

_PUBLISHED_COMPETITION_BY_ID_SQL = """
    SELECT
        id,
        name,
        description,
        place,
        price,
        event_date,
        application_deadline,
        city,
        short_description,
        directions,
        poster_url,
        rules_url,
        is_published,
        updated_at
    FROM competitions
    WHERE id = %s AND is_published = TRUE
"""


async def get_published_competitions(
    limit: int | None = None,
    *,
    pool: DatabasePool | None,
) -> list[CompetitionRow]:
    if limit is not None and limit <= 0:
        return []

    query = _PUBLISHED_COMPETITIONS_SQL
    params: tuple[int, ...] | None = None

    if limit is not None:
        query = _PUBLISHED_COMPETITIONS_WITH_LIMIT_SQL
        params = (limit,)

    async with get_connection(pool) as connection:
        async with connection.cursor() as cursor:
            await cursor.execute(query, params)
            rows = await cursor.fetchall()

    return [dict(row) for row in rows]


async def get_related_published_competitions(
    competition_id: int,
    *,
    city: str | None,
    reference_date: date,
    limit: int,
    pool: DatabasePool | None,
) -> list[CompetitionRow]:
    if competition_id <= 0 or limit <= 0:
        return []

    async with get_connection(pool) as connection:
        async with connection.cursor() as cursor:
            await cursor.execute(
                _RELATED_COMPETITIONS_SQL,
                (
                    competition_id,
                    city,
                    reference_date,
                    reference_date,
                    limit,
                ),
            )
            rows = await cursor.fetchall()

    return [dict(row) for row in rows]


async def get_published_competition_by_id(
    competition_id: int,
    *,
    pool: DatabasePool | None,
) -> CompetitionRow | None:
    if competition_id <= 0:
        return None

    async with get_connection(pool) as connection:
        async with connection.cursor() as cursor:
            await cursor.execute(
                _PUBLISHED_COMPETITION_BY_ID_SQL,
                (competition_id,),
            )
            row = await cursor.fetchone()

    return dict(row) if row is not None else None
