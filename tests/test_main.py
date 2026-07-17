import asyncio

from app import main
from app.database import DatabaseUnavailableError


def test_homepage_faq_is_limited_to_five(monkeypatch):
    async def get_faq_items():
        return [{"id": item} for item in range(1, 8)]

    monkeypatch.setattr(main, "get_faq_items", get_faq_items)

    items, unavailable = asyncio.run(main._load_faq_for_homepage())

    assert [item["id"] for item in items] == [1, 2, 3, 4, 5]
    assert unavailable is False


def test_homepage_loads_competitions_and_faq_independently(monkeypatch):
    async def get_featured_competitions():
        return [{"id": 7}]

    async def get_faq_items():
        raise DatabaseUnavailableError("Database is unavailable")

    monkeypatch.setattr(
        main,
        "get_featured_competitions",
        get_featured_competitions,
    )
    monkeypatch.setattr(main, "get_faq_items", get_faq_items)

    async def load_homepage_sections():
        return await asyncio.gather(
            main._load_featured_for_homepage(),
            main._load_faq_for_homepage(),
        )

    competitions_result, faq_result = asyncio.run(load_homepage_sections())

    assert competitions_result == ([{"id": 7}], False)
    assert faq_result == ([], True)


def test_faq_route_is_registered():
    assert "/faq" in main.app.openapi()["paths"]
