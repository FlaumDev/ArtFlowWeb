from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.cache import AsyncTTLCache
from app.config import Settings, settings
from app.database import (
    DatabaseUnavailableError,
    check_database_connection,
    close_database_pool,
    open_database_pool,
)
from app.routers.competitions import router as competitions_router
from app.routers.faq import router as faq_router
from app.security import (
    DOCS_CONTENT_SECURITY_POLICY,
    SECURITY_HEADERS,
    SecurityHeadersMiddleware,
)
from app.services.competitions import get_featured_competitions
from app.services.faq import get_faq_items
from app.site_content import get_site_content
from app.web import page_context, request_settings


logger = logging.getLogger(__name__)
templates = Jinja2Templates(directory="templates")
core_router = APIRouter()
_health_db_cache: AsyncTTLCache[str, bool] = AsyncTTLCache(
    ttl_seconds=5,
    max_entries=1,
)


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    await open_database_pool(application.state.settings)
    try:
        yield
    finally:
        await close_database_pool()


async def _load_featured_for_homepage(app_settings: Settings | None = None):
    try:
        if app_settings is None:
            competitions = await get_featured_competitions()
        else:
            competitions = await get_featured_competitions(
                app_settings=app_settings
            )
        return competitions, False
    except DatabaseUnavailableError:
        return [], True


async def _load_faq_for_homepage():
    try:
        return (await get_faq_items())[:5], False
    except DatabaseUnavailableError:
        return [], True


@core_router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    active_settings = request_settings(request)
    (
        (featured_competitions, competitions_unavailable),
        (faq_items, faq_unavailable),
    ) = await asyncio.gather(
        _load_featured_for_homepage(active_settings),
        _load_faq_for_homepage(),
    )
    status_code = 503 if competitions_unavailable else 200
    site_content = get_site_content()
    context = page_context(
        request,
        title="ArtFlow - творческие конкурсы для детей и подростков",
        description=(
            "Творческие события ArtFlow: сценический опыт, поддержка "
            "организаторов и актуальные конкурсы для юных артистов."
        ),
        site_content=site_content,
        active_page="home",
        show_contact_section=True,
        show_floating_contact=True,
    )
    context.update(
        {
            "featured_competitions": featured_competitions,
            "competitions_unavailable": competitions_unavailable,
            "faq_items": faq_items,
            "faq_unavailable": faq_unavailable,
        }
    )
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context=context,
        status_code=status_code,
    )


@core_router.get("/health")
async def health():
    return {"status": "ok"}


@core_router.get("/health/db")
async def health_db():
    async def check() -> bool:
        try:
            await check_database_connection()
        except DatabaseUnavailableError:
            return False
        return True

    available = await _health_db_cache.get_or_load("database", check)
    if not available:
        return JSONResponse(
            status_code=503,
            content={"status": "unavailable"},
        )
    return {"status": "ok"}


def clear_health_cache() -> None:
    _health_db_cache.clear()


async def not_found(request: Request, _exc: StarletteHTTPException):
    site_content = get_site_content()
    return templates.TemplateResponse(
        request=request,
        name="404.html",
        context=page_context(
            request,
            title="Страница не найдена - ArtFlow",
            description=(
                "Запрошенная страница ArtFlow не найдена. "
                "Вернитесь к актуальному расписанию конкурсов."
            ),
            site_content=site_content,
        ),
        status_code=404,
    )


async def server_error(request: Request, exc: Exception):
    logger.error(
        "Unhandled request error",
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    site_content = get_site_content()
    response = templates.TemplateResponse(
        request=request,
        name="500.html",
        context=page_context(
            request,
            title="Ошибка сервера - ArtFlow",
            description=(
                "ArtFlow временно не может открыть эту страницу. "
                "Перейдите на главную или к списку конкурсов."
            ),
            site_content=site_content,
        ),
        status_code=500,
    )
    active_settings = request_settings(request)
    if active_settings.enable_security_headers:
        response.headers.update(SECURITY_HEADERS)
        if (
            active_settings.is_production
            and active_settings.public_https_base_url is not None
        ):
            response.headers["strict-transport-security"] = "max-age=31536000"
    return response


def create_app(app_settings: Settings | None = None) -> FastAPI:
    active_settings = app_settings or settings
    docs_url = "/docs" if active_settings.enable_docs else None
    openapi_url = "/openapi.json" if active_settings.enable_docs else None
    redoc_url = "/redoc" if active_settings.enable_docs else None

    application = FastAPI(
        title="ArtFlowWeb",
        lifespan=lifespan,
        docs_url=docs_url,
        redoc_url=redoc_url,
        openapi_url=openapi_url,
    )
    application.state.settings = active_settings
    application.mount("/static", StaticFiles(directory="static"), name="static")
    application.include_router(competitions_router)
    application.include_router(faq_router)
    application.include_router(core_router)
    application.add_exception_handler(404, not_found)
    application.add_exception_handler(Exception, server_error)
    application.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=list(active_settings.trusted_hosts),
    )
    if active_settings.enable_security_headers:
        application.add_middleware(
            SecurityHeadersMiddleware,
            enable_hsts=(
                active_settings.is_production
                and active_settings.public_https_base_url is not None
            ),
            csp_overrides=(
                {
                    "/docs": DOCS_CONTENT_SECURITY_POLICY,
                    "/redoc": DOCS_CONTENT_SECURITY_POLICY,
                }
                if active_settings.enable_docs
                else None
            ),
        )
    return application


app = create_app()
