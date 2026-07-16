from __future__ import annotations

from typing import Any

from app.database import get_connection


CompetitionRow = dict[str, Any]

_PUBLISHED_COMPETITIONS_SQL = """
    SELECT
        id,
        name,
        description,
        date,
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
        date,
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

_PUBLISHED_COMPETITION_BY_ID_SQL = """
    SELECT
        id,
        name,
        description,
        date,
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
) -> list[CompetitionRow]:
    if limit is not None and limit <= 0:
        return []

    query = _PUBLISHED_COMPETITIONS_SQL
    params: tuple[int, ...] | None = None

    if limit is not None:
        query = _PUBLISHED_COMPETITIONS_WITH_LIMIT_SQL
        params = (limit,)

    async with get_connection() as connection:
        async with connection.cursor() as cursor:
            await cursor.execute(query, params)
            rows = await cursor.fetchall()

    return [dict(row) for row in rows]


async def get_published_competition_by_id(
    competition_id: int,
) -> CompetitionRow | None:
    if competition_id <= 0:
        return None

    async with get_connection() as connection:
        async with connection.cursor() as cursor:
            await cursor.execute(
                _PUBLISHED_COMPETITION_BY_ID_SQL,
                (competition_id,),
            )
            row = await cursor.fetchone()

    return dict(row) if row is not None else None
