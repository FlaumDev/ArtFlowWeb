from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTENT_PATH = PROJECT_ROOT / "content" / "site_content.json"
STATIC_ROOT = PROJECT_ROOT / "static"

_PLACEHOLDER_MARKERS = (
    "CHANGE_ME",
    "TODO",
    "ВСТАВЬ",
    "ЗАМЕНИ",
    "НАЗВАНИЕ_",
    "INSTAGRAM_URL",
    "WHATSAPP_",
    "TELEGRAM_",
)

_DEFAULT_CONTENT: dict[str, Any] = {
    "brand": {
        "name": "ArtFlow",
        "hero_eyebrow": "Творческие конкурсы",
        "hero_title": "Сцена, на которой раскрываются таланты",
        "hero_text": "Понятные условия участия и удобный путь к заявке.",
        "about_title": "Творчество начинается со смелого шага",
        "about_text": "ArtFlow помогает участникам выбрать событие и подготовиться к выходу на сцену.",
        "footer_text": "Творческие конкурсы ArtFlow.",
    },
    "media": {
        "hero_main": "",
        "hero_main_small": "",
        "hero_main_alt": "",
        "hero_main_width": 0,
        "hero_main_height": 0,
        "hero_secondary": "",
        "hero_secondary_small": "",
        "hero_secondary_alt": "",
        "hero_secondary_width": 0,
        "hero_secondary_height": 0,
        "about": "",
        "about_small": "",
        "about_alt": "",
        "about_width": 0,
        "about_height": 0,
    },
    "contacts": {
        "email": "",
        "instagram": {"label": "", "url": ""},
        "organizers": [],
    },
    "gallery": [],
    "sections": {
        "gallery_enabled": False,
        "organizers_enabled": False,
        "instagram_enabled": False,
        "floating_contact_enabled": False,
    },
    "has_contacts": False,
}


def _text(value: Any, fallback: str = "") -> str:
    if not isinstance(value, str):
        return fallback
    normalized = value.strip()
    return normalized if normalized else fallback


def _is_placeholder(value: str) -> bool:
    normalized = value.strip().upper()
    return not normalized or normalized == "#" or any(
        marker in normalized for marker in _PLACEHOLDER_MARKERS
    )


def _web_url(value: Any) -> str:
    url = _text(value)
    if _is_placeholder(url) or any(ord(character) < 32 for character in url):
        return ""

    try:
        parsed = urlsplit(url)
    except ValueError:
        return ""

    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        return ""
    return url


def _platform_url(
    value: Any,
    *,
    allowed_hosts: set[str],
    strip_query: bool = False,
) -> str:
    url = _web_url(value)
    if not url:
        return ""

    try:
        parsed = urlsplit(url)
        hostname = (parsed.hostname or "").casefold()
        port = parsed.port
    except ValueError:
        return ""

    if (
        parsed.scheme.casefold() != "https"
        or hostname not in allowed_hosts
        or parsed.username
        or parsed.password
        or port not in {None, 443}
    ):
        return ""

    if strip_query:
        return urlunsplit(("https", parsed.netloc, parsed.path, "", ""))
    return url


def _email(value: Any) -> str:
    email = _text(value)
    if (
        _is_placeholder(email)
        or " " in email
        or email.count("@") != 1
        or any(ord(character) < 32 or ord(character) == 127 for character in email)
    ):
        return ""
    local_part, domain = email.rsplit("@", 1)
    return email if local_part and "." in domain else ""


def _local_image(value: Any) -> str:
    image_path = _text(value)
    if _is_placeholder(image_path) or not image_path.startswith("/static/images/"):
        return ""

    relative_path = image_path.removeprefix("/static/")
    candidate = (STATIC_ROOT / relative_path).resolve()
    try:
        candidate.relative_to(STATIC_ROOT.resolve())
    except ValueError:
        return ""
    return image_path if candidate.is_file() else ""


def _positive_int(value: Any) -> int:
    return value if type(value) is int and value > 0 else 0


def _section_flags(value: Any) -> dict[str, bool]:
    source = value if isinstance(value, dict) else {}
    return {
        key: source.get(key) is True
        for key in _DEFAULT_CONTENT["sections"]
    }


def _normalize_content(raw: Any) -> dict[str, Any]:
    source = raw if isinstance(raw, dict) else {}
    brand_source = source.get("brand") if isinstance(source.get("brand"), dict) else {}
    media_source = source.get("media") if isinstance(source.get("media"), dict) else {}
    contacts_source = (
        source.get("contacts") if isinstance(source.get("contacts"), dict) else {}
    )
    instagram_source = (
        contacts_source.get("instagram")
        if isinstance(contacts_source.get("instagram"), dict)
        else {}
    )

    brand = {
        key: _text(brand_source.get(key), fallback)
        for key, fallback in _DEFAULT_CONTENT["brand"].items()
    }
    media = {
        "hero_main": _local_image(media_source.get("hero_main")),
        "hero_main_small": _local_image(media_source.get("hero_main_small")),
        "hero_main_alt": _text(media_source.get("hero_main_alt")),
        "hero_main_width": _positive_int(media_source.get("hero_main_width")),
        "hero_main_height": _positive_int(media_source.get("hero_main_height")),
        "hero_secondary": _local_image(media_source.get("hero_secondary")),
        "hero_secondary_small": _local_image(
            media_source.get("hero_secondary_small")
        ),
        "hero_secondary_alt": _text(media_source.get("hero_secondary_alt")),
        "hero_secondary_width": _positive_int(
            media_source.get("hero_secondary_width")
        ),
        "hero_secondary_height": _positive_int(
            media_source.get("hero_secondary_height")
        ),
        "about": _local_image(media_source.get("about")),
        "about_small": _local_image(media_source.get("about_small")),
        "about_alt": _text(media_source.get("about_alt")),
        "about_width": _positive_int(media_source.get("about_width")),
        "about_height": _positive_int(media_source.get("about_height")),
    }

    organizers = []
    organizers_source = contacts_source.get("organizers")
    if isinstance(organizers_source, list):
        for item in organizers_source:
            if not isinstance(item, dict):
                continue
            organizer = {
                "name": _text(item.get("name")),
                "role": _text(item.get("role")),
                "note": _text(item.get("note")),
                "photo": _local_image(item.get("photo")),
                "photo_small": _local_image(item.get("photo_small")),
                "photo_alt": _text(item.get("photo_alt")),
                "photo_width": _positive_int(item.get("photo_width")),
                "photo_height": _positive_int(item.get("photo_height")),
                "whatsapp_url": _platform_url(
                    item.get("whatsapp_url"),
                    allowed_hosts={"wa.me", "api.whatsapp.com"},
                ),
                "telegram_url": _platform_url(
                    item.get("telegram_url"),
                    allowed_hosts={"t.me"},
                ),
            }
            if organizer["name"] or organizer["photo"] or organizer["whatsapp_url"] or organizer["telegram_url"]:
                organizers.append(organizer)

    gallery = []
    gallery_source = source.get("gallery")
    if isinstance(gallery_source, list):
        for item in gallery_source:
            if not isinstance(item, dict):
                continue
            src = _local_image(item.get("src"))
            if not src:
                continue
            gallery.append(
                {
                    "src": src,
                    "src_small": _local_image(item.get("src_small")),
                    "alt": _text(
                        item.get("alt"),
                        "Фотография творческого события ArtFlow",
                    ),
                    "caption": _text(item.get("caption")),
                    "width": _positive_int(item.get("width")),
                    "height": _positive_int(item.get("height")),
                }
            )

    contacts = {
        "email": _email(contacts_source.get("email")),
        "instagram": {
            "label": _text(instagram_source.get("label")),
            "url": _platform_url(
                instagram_source.get("url"),
                allowed_hosts={"instagram.com", "www.instagram.com"},
                strip_query=True,
            ),
        },
        "organizers": organizers,
    }
    sections = _section_flags(source.get("sections"))
    has_contacts = bool(
        contacts["email"]
        or contacts["instagram"]["url"]
        or any(
            organizer["whatsapp_url"] or organizer["telegram_url"]
            for organizer in organizers
        )
    )

    return {
        "brand": brand,
        "media": media,
        "contacts": contacts,
        "gallery": gallery,
        "sections": sections,
        "has_contacts": has_contacts,
    }


def load_site_content(path: str | Path = DEFAULT_CONTENT_PATH) -> dict[str, Any]:
    try:
        with Path(path).open(encoding="utf-8") as content_file:
            raw = json.load(content_file)
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError):
        raw = {}
    return _normalize_content(raw)


@lru_cache(maxsize=4)
def _load_cached(path: str) -> dict[str, Any]:
    return load_site_content(path)


def get_site_content(path: str | Path = DEFAULT_CONTENT_PATH) -> dict[str, Any]:
    return _load_cached(str(Path(path).resolve()))


def clear_site_content_cache() -> None:
    _load_cached.cache_clear()
