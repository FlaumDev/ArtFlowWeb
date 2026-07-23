from fastapi import Request
from fastapi.responses import HTMLResponse

from app import main as main_module
from app.config import Settings
from app.routers import competitions as competition_routes
from app.routers import faq as faq_routes
from app.site_content import get_site_content
from app.web import page_context


COMPETITIONS = [
    {
        "id": 7,
        "name": "Большой творческий конкурс ArtFlow",
        "short_description": "Сценическое событие для солистов и коллективов.",
        "description": "Участники представляют подготовленный номер на сцене ArtFlow.",
        "event_date": "05.09.2026",
        "application_deadline": "01.09.2026",
        "city": "Алматы",
        "place": "Городская сцена",
        "directions": ["Вокал", "Современная хореография для больших коллективов"],
        "poster_url": "/static/images/e2e-missing-poster.webp",
        "rules_url": "https://example.test/rules",
        "price": "12 000 ₸",
        "registration_is_open": True,
        "telegram_url": "https://t.me/ArtFlowBot?start=competition_7",
    },
    {
        "id": 8,
        "name": "Музыкальная палитра",
        "short_description": "Конкурс инструментального исполнительства.",
        "description": "Открытая сцена для юных исполнителей.",
        "event_date": "12.10.2026",
        "application_deadline": "01.08.2026",
        "city": "Караганда",
        "place": "Концертный зал",
        "directions": ["Фортепиано", "Народные инструменты"],
        "poster_url": "/static/images/gallery-02-800.webp",
        "rules_url": None,
        "price": "10 000 ₸",
        "registration_is_open": False,
        "telegram_url": None,
    },
    {
        "id": 9,
        "name": "Театральная весна для юных артистов и творческих студий",
        "short_description": "Спектакли, художественное слово и сценические миниатюры.",
        "description": "Творческая встреча театральных коллективов и чтецов.",
        "event_date": "18.11.2026",
        "application_deadline": "10.11.2026",
        "city": "Астана",
        "place": "Молодёжный театр",
        "directions": ["Театр", "Художественное слово"],
        "poster_url": None,
        "rules_url": None,
        "price": "Уточняется",
        "registration_is_open": True,
        "telegram_url": "https://t.me/ArtFlowBot?start=competition_9",
    },
]

FAQ_ITEMS = [
    {
        "id": 1,
        "question": "Как подать заявку?",
        "answer": "Выберите конкурс и перейдите в Telegram по кнопке заявки.",
    },
    {
        "id": 2,
        "question": "Можно ли участвовать коллективом?",
        "answer": "Доступные форматы указаны в положении выбранного конкурса.",
    },
]


async def featured_competitions(
    limit: int = 3,
    app_settings=None,
    database_pool=None,
    cache=None,
):
    return COMPETITIONS[:limit]


async def all_competitions(
    app_settings=None,
    database_pool=None,
    cache=None,
):
    return COMPETITIONS


async def one_competition(
    competition_id: int,
    app_settings=None,
    database_pool=None,
    cache=None,
):
    return next(
        (item for item in COMPETITIONS if item["id"] == competition_id),
        None,
    )


async def faq_items(database_pool=None, cache=None):
    return FAQ_ITEMS


main_module.get_featured_competitions = featured_competitions
main_module.get_faq_items = faq_items
competition_routes.get_competitions = all_competitions
competition_routes.get_competition_by_id = one_competition
faq_routes.get_faq_items = faq_items

E2E_SETTINGS = Settings(
    database_url=None,
    db_host=None,
    db_name=None,
    db_user=None,
    db_password=None,
    db_port="5432",
    bot_username="ArtFlowBot",
    app_env="test",
    base_url="http://127.0.0.1",
    allowed_hosts=("127.0.0.1", "localhost"),
    enable_docs=False,
    enable_security_headers=True,
    app_timezone="Asia/Almaty",
)

app = main_module.create_app(E2E_SETTINGS)


@app.get("/__e2e/500", response_class=HTMLResponse, include_in_schema=False)
async def e2e_server_error() -> None:
    raise RuntimeError("E2E controlled error")


@app.get("/__e2e/503", response_class=HTMLResponse, include_in_schema=False)
async def e2e_unavailable(request: Request) -> HTMLResponse:
    site_content = get_site_content()
    return main_module.templates.TemplateResponse(
        request=request,
        name="503.html",
        context=page_context(
            request,
            title="Конкурсы временно недоступны - ArtFlow",
            description="Контролируемая тестовая страница недоступности.",
            site_content=site_content,
            active_page="competitions",
        ),
        status_code=503,
    )
