from __future__ import annotations

from typing import Any

from app.repositories import faq as faq_repository


FaqItem = dict[str, Any]

_DEFAULT_ANSWER = "Ответ будет добавлен организаторами позже."


def _text(value: Any) -> str | None:
    if value is None:
        return None

    normalized = str(value).strip()
    return normalized or None


async def get_faq_items() -> list[FaqItem]:
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
