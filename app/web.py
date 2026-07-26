from __future__ import annotations

from typing import Any

from fastapi import Request

from app.cache import ApplicationCaches
from app.clock import current_date
from app.config import Settings, settings
from app.database import DatabasePool
from app.seo import (
    DEFAULT_DESCRIPTION,
    DEFAULT_IMAGE_PATH,
    SITE_LOCALE,
    SITE_NAME,
    meta_description,
    plain_text,
)


def request_settings(request: Request) -> Settings:
    return getattr(request.app.state, "settings", settings)


def request_database_pool(request: Request) -> DatabasePool | None:
    return getattr(request.app.state, "database_pool", None)


def request_caches(request: Request) -> ApplicationCaches:
    return request.app.state.caches


def page_context(
    request: Request,
    *,
    title: str,
    description: str,
    site_content: dict[str, Any],
    active_page: str | None = None,
    show_contact_section: bool = False,
    show_floating_contact: bool = False,
    og_image: str | None = None,
    fallback_image: str | None = None,
    indexable: bool = True,
    og_type: str = "website",
) -> dict[str, Any]:
    active_settings = request_settings(request)
    public_base_url = active_settings.public_https_base_url
    canonical_url = (
        f"{public_base_url}{request.url.path}"
        if public_base_url and indexable
        else None
    )

    selected_image = og_image if og_image and og_image.startswith("https://") else None
    selected_image = (
        selected_image
        or fallback_image
        or site_content["media"].get("hero_main")
        or DEFAULT_IMAGE_PATH
    )
    if selected_image and selected_image.startswith("/static/"):
        image_base = public_base_url or str(request.base_url).rstrip("/")
        selected_image = f"{image_base}{selected_image}"
    elif selected_image and not selected_image.startswith("https://"):
        selected_image = None

    seo_title = plain_text(title) or SITE_NAME
    seo_description = meta_description(description, DEFAULT_DESCRIPTION)
    return {
        "request": request,
        "title": seo_title,
        "seo_title": seo_title,
        "meta_description": seo_description,
        "seo_description": seo_description,
        "robots": "index, follow" if indexable else "noindex, nofollow",
        "og_title": seo_title,
        "og_description": seo_description,
        "og_image": selected_image,
        "og_url": canonical_url,
        "og_type": og_type,
        "og_site_name": SITE_NAME,
        "og_locale": SITE_LOCALE,
        "twitter_card": "summary_large_image",
        "canonical_url": canonical_url,
        "structured_data": [],
        "current_year": current_date(active_settings).year,
        "telegram_url": active_settings.telegram_url,
        "site_content": site_content,
        "active_page": active_page,
        "show_contact_section": show_contact_section,
        "show_floating_contact": show_floating_contact,
    }
