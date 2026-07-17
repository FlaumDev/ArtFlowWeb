import asyncio
import re
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

import pytest

from app.database import DatabaseUnavailableError
from app.repositories import faq as faq_repository
from app.services import faq as faq_service


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def faq_row(**overrides):
    row = {
        "id": 1,
        "question": "Как подать заявку?",
        "answer": "Откройте страницу конкурса.",
        "create_at": datetime(2026, 7, 17, 12, 0),
    }
    row.update(overrides)
    return row


def set_repository_rows(monkeypatch, rows):
    async def get_all_faq():
        return rows

    monkeypatch.setattr(faq_service.faq_repository, "get_all_faq", get_all_faq)


def test_faq_question_and_answer_are_trimmed(monkeypatch):
    set_repository_rows(
        monkeypatch,
        [faq_row(question="  Как подать заявку?  ", answer="  В Telegram.  ")],
    )

    assert asyncio.run(faq_service.get_faq_items()) == [
        {
            "id": 1,
            "question": "Как подать заявку?",
            "answer": "В Telegram.",
        }
    ]


@pytest.mark.parametrize("answer", [None, "", "   "])
def test_empty_faq_answer_gets_public_fallback(monkeypatch, answer):
    set_repository_rows(monkeypatch, [faq_row(answer=answer)])

    result = asyncio.run(faq_service.get_faq_items())

    assert result[0]["answer"] == "Ответ будет добавлен организаторами позже."


@pytest.mark.parametrize("question", [None, "", "   "])
def test_empty_faq_question_is_excluded(monkeypatch, question):
    set_repository_rows(
        monkeypatch,
        [faq_row(id=1, question=question), faq_row(id=2)],
    )

    result = asyncio.run(faq_service.get_faq_items())

    assert [item["id"] for item in result] == [2]


def test_faq_order_from_repository_is_preserved(monkeypatch):
    set_repository_rows(
        monkeypatch,
        [faq_row(id=2), faq_row(id=5), faq_row(id=9)],
    )

    result = asyncio.run(faq_service.get_faq_items())

    assert [item["id"] for item in result] == [2, 5, 9]


def test_empty_faq_list_stays_empty(monkeypatch):
    set_repository_rows(monkeypatch, [])

    assert asyncio.run(faq_service.get_faq_items()) == []


def test_faq_database_error_does_not_reveal_secret(monkeypatch):
    @asynccontextmanager
    async def unavailable_connection():
        raise DatabaseUnavailableError(
            "postgresql://public_user:very-secret-password@example.invalid/db"
        )
        yield

    monkeypatch.setattr(faq_repository, "get_connection", unavailable_connection)

    with pytest.raises(DatabaseUnavailableError) as error:
        asyncio.run(faq_repository.get_all_faq())

    assert str(error.value) == "Database is unavailable"
    assert "secret" not in str(error.value).lower()


def test_faq_repository_query_is_select_only():
    normalized = " ".join(faq_repository._ALL_FAQ_SQL.upper().split())
    tokens = set(re.findall(r"[A-Z_]+", normalized))
    forbidden = {"INSERT", "UPDATE", "DELETE", "CREATE", "ALTER", "DROP", "TRUNCATE"}

    assert normalized.startswith("SELECT ID, QUESTION, ANSWER, CREATE_AT FROM FAQ")
    assert normalized.endswith("ORDER BY ID ASC")
    assert "SELECT *" not in normalized
    assert not forbidden.intersection(tokens)


def test_faq_template_uses_native_accordion_and_escaped_output():
    component = (PROJECT_ROOT / "templates/components/faq_list.html").read_text(
        encoding="utf-8"
    )

    assert "<details>" in component
    assert "<summary>" in component
    assert "| safe" not in component
    assert "|safe" not in component
