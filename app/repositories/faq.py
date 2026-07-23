from __future__ import annotations

from typing import Any

from app.database import DatabasePool, DatabaseUnavailableError, get_connection


FaqRow = dict[str, Any]

_ALL_FAQ_SQL = """
    SELECT
        id,
        question,
        answer,
        create_at
    FROM faq
    ORDER BY id ASC
"""


async def get_all_faq(*, pool: DatabasePool | None) -> list[FaqRow]:
    try:
        async with get_connection(pool) as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(_ALL_FAQ_SQL)
                rows = await cursor.fetchall()
    except DatabaseUnavailableError:
        raise DatabaseUnavailableError("Database is unavailable") from None

    return [dict(row) for row in rows]
