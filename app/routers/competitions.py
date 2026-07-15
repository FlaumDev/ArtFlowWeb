from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates


router = APIRouter()
templates = Jinja2Templates(directory="templates")


COMPETITIONS = [
    {
        "id": 1,
        "title": "ArtFlow Весна",
        "status": "Прием заявок открыт",
        "city": "Москва",
        "date": "15 мая 2026",
        "deadline": "до 1 мая 2026",
        "place": "Культурный центр ArtFlow",
        "directions": ["Вокал", "Хореография"],
        "price": "от 2500 рублей",
        "short_description": "Очный конкурс для вокальных и танцевальных номеров.",
        "description": (
            "Тестовая карточка конкурса для первого каркаса сайта. "
            "В дальнейшем данные будут приходить из публичной таблицы конкурсов."
        ),
        "telegram_url": "https://t.me/BOT_USERNAME?start=competition_1",
    },
    {
        "id": 2,
        "title": "ArtFlow Лето",
        "status": "Скоро открытие регистрации",
        "city": "Санкт-Петербург",
        "date": "20 июня 2026",
        "deadline": "будет объявлен позже",
        "place": "Городская творческая площадка",
        "directions": ["Инструментальное исполнение", "Театр"],
        "price": "уточняется",
        "short_description": "Летний конкурс для сценических и музыкальных направлений.",
        "description": (
            "Временное описание для демонстрации страницы конкурса без подключения "
            "к базе данных и внешним сервисам."
        ),
        "telegram_url": "https://t.me/BOT_USERNAME?start=competition_2",
    },
    {
        "id": 3,
        "title": "ArtFlow Онлайн",
        "status": "Прием заявок открыт",
        "city": "Онлайн",
        "date": "30 июля 2026",
        "deadline": "до 15 июля 2026",
        "place": "Дистанционный формат",
        "directions": ["Вокал", "Хореография", "Инструментальное исполнение"],
        "price": "от 1500 рублей",
        "short_description": "Дистанционный формат для участников из разных городов.",
        "description": (
            "Тестовый онлайн-конкурс в списке MVP. Реальные условия, сроки и "
            "стоимость должны быть подтверждены перед публикацией."
        ),
        "telegram_url": "https://t.me/BOT_USERNAME?start=competition_3",
    },
]


@router.get("/competitions", response_class=HTMLResponse)
async def competitions(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="competitions.html",
        context={
            "request": request,
            "title": "Конкурсы ArtFlow",
            "competitions": COMPETITIONS,
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
            "title": competition["title"],
            "competition": competition,
        },
    )
