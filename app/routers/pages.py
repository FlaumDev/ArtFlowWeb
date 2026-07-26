from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.seo import breadcrumb_structured_data
from app.site_content import get_site_content
from app.web import page_context, request_settings


router = APIRouter()
templates = Jinja2Templates(directory="templates")


def _information_page_context(
    request: Request,
    *,
    title: str,
    description: str,
    active_page: str,
    current_label: str,
    current_path: str,
) -> dict[str, Any]:
    context = page_context(
        request,
        title=title,
        description=description,
        site_content=get_site_content(),
        active_page=active_page,
        show_contact_section=True,
        show_floating_contact=True,
    )
    context["breadcrumbs"] = [
        {"label": "Главная", "url": request.url_for("index")},
        {"label": current_label, "url": None},
    ]
    breadcrumb = breadcrumb_structured_data(
        [("Главная", "/"), (current_label, current_path)],
        base_url=request_settings(request).public_https_base_url,
    )
    context["structured_data"] = [breadcrumb] if breadcrumb else []
    return context


@router.get("/about", response_class=HTMLResponse, name="about")
async def about(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="about.html",
        context=_information_page_context(
            request,
            title="О проекте ArtFlow — конкурсы и подача заявки",
            description=(
                "ArtFlow помогает участникам, родителям и педагогам находить "
                "опубликованные творческие конкурсы, изучать условия и переходить "
                "к заявке в Telegram."
            ),
            active_page="about",
            current_label="О проекте",
            current_path="/about",
        ),
    )


@router.get(
    "/how-to-participate",
    response_class=HTMLResponse,
    name="how_to_participate",
)
async def how_to_participate(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="how_to_participate.html",
        context=_information_page_context(
            request,
            title="Как принять участие в конкурсе ArtFlow",
            description=(
                "Пошаговая инструкция: как выбрать конкурс ArtFlow, проверить "
                "условия и перейти к подаче заявки через Telegram-бот."
            ),
            active_page="how-to-participate",
            current_label="Как принять участие",
            current_path="/how-to-participate",
        ),
    )
