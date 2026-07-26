from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.database import DatabaseUnavailableError
from app.seo import breadcrumb_structured_data
from app.services.faq import get_faq_items
from app.site_content import get_site_content
from app.web import (
    page_context,
    request_caches,
    request_database_pool,
    request_settings,
)


router = APIRouter()
templates = Jinja2Templates(directory="templates")


@router.get("/faq", response_class=HTMLResponse, name="faq")
async def faq(request: Request) -> HTMLResponse:
    load_error = False
    status_code = 200
    database_pool = request_database_pool(request)
    caches = request_caches(request)

    try:
        faq_items = await get_faq_items(
            database_pool=database_pool,
            cache=caches.faq,
        )
    except DatabaseUnavailableError:
        faq_items = []
        load_error = True
        status_code = 503

    site_content = get_site_content()
    context = page_context(
        request,
        title="Частые вопросы об участии в конкурсах | ArtFlow",
        description=(
            "Ответы ArtFlow на частые вопросы об участии в творческих "
            "конкурсах, подготовке, подаче заявки и организации событий."
        ),
        site_content=site_content,
        active_page="faq",
        indexable=status_code == 200,
    )
    context["breadcrumbs"] = [
        {"label": "Главная", "url": request.url_for("index")},
        {"label": "FAQ", "url": None},
    ]
    breadcrumb = breadcrumb_structured_data(
        [("Главная", "/"), ("FAQ", "/faq")],
        base_url=request_settings(request).public_https_base_url,
    )
    context["structured_data"] = (
        [breadcrumb] if breadcrumb and status_code == 200 else []
    )
    context.update({"faq_items": faq_items, "load_error": load_error})
    return templates.TemplateResponse(
        request=request,
        name="faq.html",
        context=context,
        status_code=status_code,
    )
