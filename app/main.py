import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import settings
from app.database import (
    DatabaseUnavailableError,
    check_database_connection,
    close_database_pool,
    open_database_pool,
)
from app.routers.competitions import router as competitions_router
from app.routers.faq import router as faq_router
from app.services.competitions import get_featured_competitions
from app.services.faq import get_faq_items


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    await open_database_pool()
    try:
        yield
    finally:
        await close_database_pool()


app = FastAPI(title="ArtFlowWeb", lifespan=lifespan)

templates = Jinja2Templates(directory="templates")

app.mount("/static", StaticFiles(directory="static"), name="static")
app.include_router(competitions_router)
app.include_router(faq_router)


async def _load_featured_for_homepage():
    try:
        return await get_featured_competitions(), False
    except DatabaseUnavailableError:
        return [], True


async def _load_faq_for_homepage():
    try:
        return (await get_faq_items())[:5], False
    except DatabaseUnavailableError:
        return [], True


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    (
        (featured_competitions, competitions_unavailable),
        (faq_items, faq_unavailable),
    ) = await asyncio.gather(
        _load_featured_for_homepage(),
        _load_faq_for_homepage(),
    )

    status_code = 503 if competitions_unavailable else 200

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "request": request,
            "title": "ArtFlow - творческие конкурсы",
            "current_year": date.today().year,
            "featured_competitions": featured_competitions,
            "competitions_unavailable": competitions_unavailable,
            "faq_items": faq_items,
            "faq_unavailable": faq_unavailable,
            "telegram_url": settings.telegram_url,
        },
        status_code=status_code,
    )


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/health/db")
async def health_db():
    try:
        await check_database_connection()
    except DatabaseUnavailableError:
        return JSONResponse(
            status_code=503,
            content={"status": "unavailable"},
        )

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
            "telegram_url": settings.telegram_url,
        },
        status_code=404,
    )
