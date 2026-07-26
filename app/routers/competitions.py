from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.database import DatabaseUnavailableError
from app.seo import (
    DEFAULT_IMAGE_PATH,
    breadcrumb_structured_data,
    competition_meta_description,
    competition_structured_data,
    plain_text,
)
from app.services.competitions import (
    get_competition_by_id,
    get_competitions,
    get_related_competitions,
)
from app.site_content import get_site_content
from app.web import (
    page_context,
    request_caches,
    request_database_pool,
    request_settings,
)


router = APIRouter()
templates = Jinja2Templates(directory="templates")


@router.get("/competitions", response_class=HTMLResponse)
async def competitions(request: Request) -> HTMLResponse:
    load_error = False
    status_code = 200
    active_settings = request_settings(request)
    database_pool = request_database_pool(request)
    caches = request_caches(request)

    try:
        competition_items = await get_competitions(
            app_settings=active_settings,
            database_pool=database_pool,
            cache=caches.competitions,
        )
    except DatabaseUnavailableError:
        competition_items = []
        load_error = True
        status_code = 503

    site_content = get_site_content()
    context = page_context(
        request,
        title="Конкурсы и фестивали ArtFlow — подать заявку онлайн",
        description=(
            "Опубликованные конкурсы и фестивали ArtFlow: даты, города, "
            "направления, условия участия и сроки подачи заявки."
        ),
        site_content=site_content,
        active_page="competitions",
        show_contact_section=True,
        show_floating_contact=True,
        indexable=status_code == 200,
    )
    context["breadcrumbs"] = [
        {"label": "Главная", "url": request.url_for("index")},
        {"label": "Конкурсы", "url": None},
    ]
    breadcrumb = breadcrumb_structured_data(
        [("Главная", "/"), ("Конкурсы", "/competitions")],
        base_url=active_settings.public_https_base_url,
    )
    context["structured_data"] = (
        [breadcrumb] if breadcrumb and status_code == 200 else []
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
async def competition_detail(
    request: Request,
    competition_id: int,
) -> HTMLResponse:
    active_settings = request_settings(request)
    database_pool = request_database_pool(request)
    caches = request_caches(request)
    try:
        competition = await get_competition_by_id(
            competition_id,
            app_settings=active_settings,
            database_pool=database_pool,
            cache=caches.competition_details,
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
                indexable=False,
            ),
            status_code=503,
        )

    if competition is None:
        raise HTTPException(status_code=404, detail="Competition not found")

    source = competition.get("seo_source")
    source = source if isinstance(source, dict) else {}
    try:
        related_competitions = await get_related_competitions(
            competition_id,
            source.get("city"),
            app_settings=active_settings,
            database_pool=database_pool,
            cache=caches.competitions,
        )
    except DatabaseUnavailableError:
        related_competitions = []

    site_content = get_site_content()
    competition_name = plain_text(competition.get("name")) or "Конкурс ArtFlow"
    context = page_context(
        request,
        title=f"{competition_name} — условия участия | ArtFlow",
        description=competition_meta_description(competition),
        site_content=site_content,
        active_page="competitions",
        og_image=competition["poster_url"],
        fallback_image=DEFAULT_IMAGE_PATH,
    )
    context["structured_data"] = competition_structured_data(
        competition,
        base_url=active_settings.public_https_base_url,
        canonical_url=context["canonical_url"],
        image_url=context["og_image"],
    )
    context["breadcrumbs"] = [
        {"label": "Главная", "url": request.url_for("index")},
        {"label": "Конкурсы", "url": request.url_for("competitions")},
        {"label": competition_name, "url": None},
    ]
    context["competition"] = competition
    context["related_competitions"] = related_competitions
    return templates.TemplateResponse(
        request=request,
        name="competition_detail.html",
        context=context,
    )
