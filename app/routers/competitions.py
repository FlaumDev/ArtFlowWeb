from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.database import DatabaseUnavailableError
from app.services.competitions import (
    get_competition_by_id,
    get_competitions,
)
from app.site_content import get_site_content
from app.web import page_context, request_settings


router = APIRouter()
templates = Jinja2Templates(directory="templates")


@router.get("/competitions", response_class=HTMLResponse)
async def competitions(request: Request):
    load_error = False
    status_code = 200
    active_settings = request_settings(request)

    try:
        competition_items = await get_competitions(
            app_settings=active_settings
        )
    except DatabaseUnavailableError:
        competition_items = []
        load_error = True
        status_code = 503

    site_content = get_site_content()
    context = page_context(
        request,
        title="Конкурсы ArtFlow - расписание и условия",
        description=(
            "Актуальные конкурсы ArtFlow: даты, города, направления, "
            "стоимость и сроки подачи заявки."
        ),
        site_content=site_content,
        active_page="competitions",
        show_contact_section=True,
        show_floating_contact=True,
    )
    context.update(
        {
            "competitions": competition_items,
            "load_error": load_error,
        }
    )
    return templates.TemplateResponse(
        request=request,
        name="competitions.html",
        context=context,
        status_code=status_code,
    )


@router.get("/competitions/{competition_id}", response_class=HTMLResponse)
async def competition_detail(request: Request, competition_id: int):
    active_settings = request_settings(request)
    try:
        competition = await get_competition_by_id(
            competition_id,
            app_settings=active_settings,
        )
    except DatabaseUnavailableError:
        site_content = get_site_content()
        return templates.TemplateResponse(
            request=request,
            name="503.html",
            context=page_context(
                request,
                title="Конкурсы временно недоступны - ArtFlow",
                description=(
                    "Расписание ArtFlow временно недоступно. "
                    "Попробуйте открыть страницу немного позже."
                ),
                site_content=site_content,
                active_page="competitions",
            ),
            status_code=503,
        )

    if competition is None:
        raise HTTPException(status_code=404, detail="Competition not found")

    site_content = get_site_content()
    context = page_context(
        request,
        title=f"{competition['name']} - ArtFlow",
        description=(
            f"{competition['short_description']} "
            f"Дата: {competition['event_date']}, город: {competition['city']}."
        ),
        site_content=site_content,
        active_page="competitions",
        og_image=competition["poster_url"],
    )
    context["competition"] = competition
    return templates.TemplateResponse(
        request=request,
        name="competition_detail.html",
        context=context,
    )
