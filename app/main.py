from datetime import date

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.routers.competitions import (
    TELEGRAM_URL,
    get_featured_competitions,
    router as competitions_router,
)


app = FastAPI(title="ArtFlowWeb")

templates = Jinja2Templates(directory="templates")

app.mount("/static", StaticFiles(directory="static"), name="static")
app.include_router(competitions_router)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "request": request,
            "title": "ArtFlow - творческие конкурсы",
            "current_year": date.today().year,
            "featured_competitions": get_featured_competitions(),
            "telegram_url": TELEGRAM_URL,
        },
    )


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.exception_handler(404)
async def not_found(request: Request, exc: StarletteHTTPException):
    return templates.TemplateResponse(
        request=request,
        name="404.html",
        context={
            "request": request,
            "title": "Страница не найдена",
            "current_year": date.today().year,
            "telegram_url": TELEGRAM_URL,
        },
        status_code=404,
    )
