from __future__ import annotations

from typing import Any

from app.cache import AsyncTTLCache
from app.repositories import faq as faq_repository


FaqItem = dict[str, Any]

_DEFAULT_ANSWER = "Ответ будет добавлен организаторами позже."
_faq_cache: AsyncTTLCache[str, list[FaqItem]] = AsyncTTLCache(
    ttl_seconds=30,
    max_entries=2,
)


def _text(value: Any) -> str | None:
    if value is None:
        return None

    normalized = str(value).strip()
    return normalized or None


async def get_faq_items() -> list[FaqItem]:
    async def load() -> list[FaqItem]:
        rows = await faq_repository.get_all_faq()
        items: list[FaqItem] = []

        for row in rows:
            question = _text(row.get("question"))
            if question is None:
                continue

            items.append(
                {
                    "id": row.get("id"),
                    "question": question,
                    "answer": _text(row.get("answer")) or _DEFAULT_ANSWER,
                }
            )

        return items

    return await _faq_cache.get_or_load("all", load)


def clear_faq_cache() -> None:
    _faq_cache.clear()
