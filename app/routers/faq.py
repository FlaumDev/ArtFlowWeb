from datetime import date

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.database import DatabaseUnavailableError
from app.services.faq import get_faq_items


router = APIRouter()
templates = Jinja2Templates(directory="templates")


@router.get("/faq", response_class=HTMLResponse, name="faq")
async def faq(request: Request):
    load_error = False
    status_code = 200

    try:
        faq_items = await get_faq_items()
    except DatabaseUnavailableError:
        faq_items = []
        load_error = True
        status_code = 503

    return templates.TemplateResponse(
        request=request,
        name="faq.html",
        context={
            "request": request,
            "title": "Частые вопросы - ArtFlow",
            "current_year": date.today().year,
            "faq_items": faq_items,
            "load_error": load_error,
            "telegram_url": settings.telegram_url,
        },
        status_code=status_code,
    )
