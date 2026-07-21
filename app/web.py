from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import Request

from app.config import Settings, settings


def request_settings(request: Request) -> Settings:
    return getattr(request.app.state, "settings", settings)


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
) -> dict[str, Any]:
    active_settings = request_settings(request)
    public_base_url = active_settings.public_https_base_url
    canonical_url = (
        f"{public_base_url}{request.url.path}" if public_base_url else None
    )

    selected_image = og_image if og_image and og_image.startswith("https://") else None
    selected_image = selected_image or site_content["media"].get("hero_main")
    if selected_image and selected_image.startswith("/static/"):
        image_base = public_base_url or str(request.base_url).rstrip("/")
        selected_image = f"{image_base}{selected_image}"
    elif selected_image and not selected_image.startswith("https://"):
        selected_image = None

    return {
        "request": request,
        "title": title,
        "meta_description": description,
        "og_title": title,
        "og_description": description,
        "og_image": selected_image,
        "canonical_url": canonical_url,
        "current_year": date.today().year,
        "telegram_url": active_settings.telegram_url,
        "site_content": site_content,
        "active_page": active_page,
        "show_contact_section": show_contact_section,
        "show_floating_contact": show_floating_contact,
    }
