from datetime import date

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates


router = APIRouter()
templates = Jinja2Templates(directory="templates")

TELEGRAM_URL = "https://t.me/BOT_USERNAME"

COMPETITIONS = [
    {
        "id": 1,
        "name": "ArtFlow Осень",
        "short_description": "Очный конкурс для вокальных, танцевальных и сценических номеров.",
        "description": (
            "Тестовый конкурс для первого публичного frontend ArtFlow. "
            "На этой странице показана структура будущей карточки: сроки, место, "
            "направления, стоимость и переход к заявке в Telegram."
        ),
        "event_date": "19 сентября 2026",
        "application_deadline": "5 сентября 2026",
        "city": "Москва",
        "place": "Культурный центр ArtFlow",
        "directions": ["Вокал", "Хореография", "Театр"],
        "poster_url": None,
        "rules_url": None,
        "price": "от 2 500 рублей",
        "registration_is_open": True,
        "telegram_url": "https://t.me/BOT_USERNAME?start=competition_1",
    },
    {
        "id": 2,
        "name": "ArtFlow Онлайн",
        "short_description": "Дистанционный формат для участников из разных городов.",
        "description": (
            "Тестовый онлайн-конкурс в списке MVP. Участник выбирает направление, "
            "изучает условия и переходит к подаче заявки в ArtFlowBot."
        ),
        "event_date": "25 августа 2026",
        "application_deadline": "10 августа 2026",
        "city": "Онлайн",
        "place": "Дистанционный формат",
        "directions": ["Вокал", "Хореография", "Инструментальное исполнение"],
        "poster_url": None,
        "rules_url": None,
        "price": "от 1 500 рублей",
        "registration_is_open": True,
        "telegram_url": "https://t.me/BOT_USERNAME?start=competition_2",
    },
    {
        "id": 3,
        "name": "ArtFlow Лето",
        "short_description": "Городской конкурс для музыкальных и сценических направлений.",
        "description": (
            "Демонстрационная карточка конкурса с закрытой регистрацией. "
            "Она нужна, чтобы проверить поведение страницы без активной кнопки заявки."
        ),
        "event_date": "2 августа 2026",
        "application_deadline": "10 июля 2026",
        "city": "Санкт-Петербург",
        "place": "Городская творческая площадка",
        "directions": ["Инструментальное исполнение", "Театр"],
        "poster_url": None,
        "rules_url": None,
        "price": "уточняется",
        "registration_is_open": False,
        "telegram_url": "https://t.me/BOT_USERNAME?start=competition_3",
    },
]


def get_featured_competitions(limit: int = 3):
    return COMPETITIONS[:limit]


@router.get("/competitions", response_class=HTMLResponse)
async def competitions(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="competitions.html",
        context={
            "request": request,
            "title": "Конкурсы ArtFlow",
            "current_year": date.today().year,
            "competitions": COMPETITIONS,
            "telegram_url": TELEGRAM_URL,
        },
    )


@router.get("/competitions/{competition_id}", response_class=HTMLResponse)
async def competition_detail(request: Request, competition_id: int):
    competition = next(
        (
            item
            for item in COMPETITIONS
            if item["id"] == competition_id
        ),
        None,
    )

    if competition is None:
        raise HTTPException(status_code=404, detail="Competition not found")

    return templates.TemplateResponse(
        request=request,
        name="competition_detail.html",
        context={
            "request": request,
            "title": competition["name"],
            "current_year": date.today().year,
            "competition": competition,
            "telegram_url": TELEGRAM_URL,
        },
    )
