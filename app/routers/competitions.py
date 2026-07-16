from datetime import date

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.database import DatabaseUnavailableError
from app.services.competitions import (
    get_competition_by_id,
    get_competitions,
)


router = APIRouter()
templates = Jinja2Templates(directory="templates")


@router.get("/competitions", response_class=HTMLResponse)
async def competitions(request: Request):
    load_error = False
    status_code = 200

    try:
        competition_items = await get_competitions()
    except DatabaseUnavailableError:
        competition_items = []
        load_error = True
        status_code = 503

    return templates.TemplateResponse(
        request=request,
        name="competitions.html",
        context={
            "request": request,
            "title": "Конкурсы ArtFlow",
            "current_year": date.today().year,
            "competitions": competition_items,
            "load_error": load_error,
            "telegram_url": settings.telegram_url,
        },
        status_code=status_code,
    )


@router.get("/competitions/{competition_id}", response_class=HTMLResponse)
async def competition_detail(request: Request, competition_id: int):
    try:
        competition = await get_competition_by_id(competition_id)
    except DatabaseUnavailableError:
        return templates.TemplateResponse(
            request=request,
            name="503.html",
            context={
                "request": request,
                "title": "Конкурсы временно недоступны",
                "current_year": date.today().year,
                "telegram_url": settings.telegram_url,
            },
            status_code=503,
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
            "telegram_url": settings.telegram_url,
        },
    )
