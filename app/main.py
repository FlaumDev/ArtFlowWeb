from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
# ElementTree only serializes application-owned values; it never parses XML input.
from xml.etree.ElementTree import (  # nosec B405
    Element,
    SubElement,
    tostring,
)

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.cache import ApplicationCaches, AsyncTTLCache
from app.config import Settings, settings
from app.database import (
    DatabasePool,
    DatabaseUnavailableError,
    check_database_connection,
    close_database_pool,
    open_database_pool,
)
from app.observability import (
    RequestLoggingMiddleware,
    create_application_logger,
    disable_duplicate_uvicorn_access_log,
)
from app.routers.competitions import router as competitions_router
from app.routers.faq import router as faq_router
from app.security import (
    DOCS_CONTENT_SECURITY_POLICY,
    SECURITY_HEADERS,
    SecurityHeadersMiddleware,
)
from app.seo import website_structured_data
from app.services.competitions import get_competitions, get_featured_competitions
from app.services.faq import get_faq_items
from app.site_content import get_site_content
from app.web import (
    page_context,
    request_caches,
    request_database_pool,
    request_settings,
)


templates = Jinja2Templates(directory="templates")
core_router = APIRouter()


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    pool = await open_database_pool(application.state.settings)
    application.state.database_pool = pool
    try:
        yield
    finally:
        await close_database_pool(pool)
        application.state.database_pool = None


async def _load_featured_for_homepage(
    app_settings: Settings | None = None,
    *,
    database_pool: DatabasePool | None = None,
    cache: AsyncTTLCache[tuple[Any, ...], list[dict[str, Any]]] | None = None,
) -> tuple[list[dict[str, Any]], bool]:
    try:
        if app_settings is None:
            competitions = await get_featured_competitions()
        else:
            competitions = await get_featured_competitions(
                app_settings=app_settings,
                database_pool=database_pool,
                cache=cache,
            )
        return competitions, False
    except DatabaseUnavailableError:
        return [], True


async def _load_faq_for_homepage(
    *,
    database_pool: DatabasePool | None = None,
    cache: AsyncTTLCache[str, list[dict[str, Any]]] | None = None,
) -> tuple[list[dict[str, Any]], bool]:
    try:
        if database_pool is None and cache is None:
            faq_items = await get_faq_items()
        else:
            faq_items = await get_faq_items(
                database_pool=database_pool,
                cache=cache,
            )
        return faq_items[:5], False
    except DatabaseUnavailableError:
        return [], True


@core_router.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    active_settings = request_settings(request)
    database_pool = request_database_pool(request)
    caches = request_caches(request)
    (
        (featured_competitions, competitions_unavailable),
        (faq_items, faq_unavailable),
    ) = await asyncio.gather(
        _load_featured_for_homepage(
            active_settings,
            database_pool=database_pool,
            cache=caches.competitions,
        ),
        _load_faq_for_homepage(
            database_pool=database_pool,
            cache=caches.faq,
        ),
    )
    status_code = 503 if competitions_unavailable else 200
    site_content = get_site_content()
    context = page_context(
        request,
        title="ArtFlow — конкурсы и фестивали для юных талантов",
        description=(
            "Творческие конкурсы и фестивали ArtFlow для детей и подростков: "
            "актуальное расписание, условия участия и переход к заявке."
        ),
        site_content=site_content,
        active_page="home",
        show_contact_section=True,
        show_floating_contact=True,
        indexable=status_code == 200,
    )
    context["structured_data"] = (
        website_structured_data(
            base_url=active_settings.public_https_base_url,
            description=context["seo_description"],
            site_content=site_content,
        )
        if status_code == 200
        else []
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
async def health() -> JSONResponse:
    return JSONResponse(
        content={"status": "ok"},
        headers={"X-Robots-Tag": "noindex, nofollow"},
    )


@core_router.get("/robots.txt", response_class=PlainTextResponse)
async def robots(request: Request) -> PlainTextResponse:
    lines = [
        "User-agent: *",
        "Allow: /",
        "Disallow: /docs",
        "Disallow: /redoc",
        "Disallow: /openapi.json",
    ]
    public_base_url = request_settings(request).public_https_base_url
    if public_base_url:
        lines.append(f"Sitemap: {public_base_url}/sitemap.xml")
    return PlainTextResponse("\n".join(lines) + "\n")


def _sitemap_document(base_url: str | None, competition_ids: list[int]) -> bytes:
    urlset = Element("urlset", xmlns="http://www.sitemaps.org/schemas/sitemap/0.9")
    if base_url:
        for path in ("/", "/competitions", "/faq"):
            url = SubElement(urlset, "url")
            SubElement(url, "loc").text = f"{base_url}{path}"
        for competition_id in competition_ids:
            url = SubElement(urlset, "url")
            SubElement(url, "loc").text = (
                f"{base_url}/competitions/{competition_id}"
            )
    return tostring(urlset, encoding="utf-8", xml_declaration=True)


@core_router.get("/sitemap.xml")
async def sitemap(request: Request) -> Response:
    active_settings = request_settings(request)
    public_base_url = active_settings.public_https_base_url
    competition_ids: list[int] = []

    if public_base_url:
        try:
            competitions = await get_competitions(
                active_settings,
                database_pool=request_database_pool(request),
                cache=request_caches(request).competitions,
            )
        except DatabaseUnavailableError:
            competitions = []
        competition_ids = list(
            dict.fromkeys(
                competition["id"]
                for competition in competitions
                if (
                    type(competition.get("id")) is int
                    and competition["id"] > 0
                    and competition.get("is_published") is not False
                )
            )
        )

    return Response(
        content=_sitemap_document(public_base_url, competition_ids),
        media_type="application/xml",
    )


@core_router.get("/health/db")
async def health_db(request: Request) -> JSONResponse:
    database_pool = request_database_pool(request)
    cache = request_caches(request).health_db

    async def check() -> bool:
        try:
            await check_database_connection(database_pool)
        except DatabaseUnavailableError:
            return False
        return True

    available = await cache.get_or_load("database", check)
    if not available:
        return JSONResponse(
            status_code=503,
            content={"status": "unavailable"},
            headers={"X-Robots-Tag": "noindex, nofollow"},
        )
    return JSONResponse(
        content={"status": "ok"},
        headers={"X-Robots-Tag": "noindex, nofollow"},
    )


def clear_application_caches(application: FastAPI) -> None:
    application.state.caches.clear()


async def not_found(
    request: Request,
    _exc: StarletteHTTPException,
) -> HTMLResponse:
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
            indexable=False,
        ),
        status_code=404,
    )


async def server_error(request: Request, _exc: Exception) -> HTMLResponse:
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
            indexable=False,
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
    request_id = getattr(request.state, "request_id", None)
    if request_id:
        response.headers["x-request-id"] = request_id
    return response


def create_app(app_settings: Settings | None = None) -> FastAPI:
    active_settings = app_settings or settings
    disable_duplicate_uvicorn_access_log()
    docs_enabled = active_settings.enable_docs and not active_settings.is_production
    docs_url = "/docs" if docs_enabled else None
    openapi_url = "/openapi.json" if docs_enabled else None
    redoc_url = "/redoc" if docs_enabled else None

    application = FastAPI(
        title="ArtFlowWeb",
        lifespan=lifespan,
        docs_url=docs_url,
        redoc_url=redoc_url,
        openapi_url=openapi_url,
    )
    application.state.settings = active_settings
    application.state.database_pool = None
    application.state.caches = ApplicationCaches()
    application.state.logger = create_application_logger(
        active_settings,
        name=f"artflow.application.{id(application):x}",
    )
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
                if docs_enabled
                else None
            ),
        )
    application.add_middleware(
        RequestLoggingMiddleware,
        logger=application.state.logger,
    )
    return application


app = create_app()
