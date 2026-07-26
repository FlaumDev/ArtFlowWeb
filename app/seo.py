from __future__ import annotations

import re
import unicodedata
from datetime import date
from html.parser import HTMLParser
from typing import Any


SITE_NAME = "ArtFlow"
SITE_LOCALE = "ru_RU"
SITE_LANGUAGE = "ru"
DEFAULT_DESCRIPTION = (
    "Творческие конкурсы ArtFlow для детей и подростков: "
    "условия участия, расписание и подача заявки."
)
DEFAULT_IMAGE_PATH = "/static/images/artflow-logo-512.png"
DESCRIPTION_LIMIT = 180

_WHITESPACE = re.compile(r"\s+")
_SUPPRESSED_TAGS = {"script", "style", "template"}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.suppressed_depth = 0

    def handle_starttag(
        self,
        tag: str,
        _attrs: list[tuple[str, str | None]],
    ) -> None:
        if tag.casefold() in _SUPPRESSED_TAGS:
            self.suppressed_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in _SUPPRESSED_TAGS and self.suppressed_depth:
            self.suppressed_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self.suppressed_depth:
            self.parts.append(data)


def plain_text(value: Any) -> str:
    if value is None:
        return ""

    parser = _TextExtractor()
    try:
        parser.feed(str(value))
        parser.close()
        text = " ".join(parser.parts)
    except (UnicodeError, ValueError):
        text = str(value)

    without_controls = "".join(
        " " if unicodedata.category(character) == "Cc" else character
        for character in text
    )
    return _WHITESPACE.sub(" ", without_controls).strip()


def meta_description(value: Any, fallback: str = DEFAULT_DESCRIPTION) -> str:
    description = plain_text(value) or plain_text(fallback) or DEFAULT_DESCRIPTION
    if len(description) <= DESCRIPTION_LIMIT:
        return description

    shortened = description[: DESCRIPTION_LIMIT + 1].rsplit(" ", 1)[0].rstrip(" ,;:-")
    if not shortened:
        shortened = description[:DESCRIPTION_LIMIT].rstrip()
    return f"{shortened}…"


def competition_meta_description(competition: dict[str, Any]) -> str:
    source = competition.get("seo_source")
    source = source if isinstance(source, dict) else {}
    name = plain_text(source.get("name") or competition.get("name")) or SITE_NAME
    description = plain_text(source.get("description"))
    if not description:
        description = (
            f"Информация о конкурсе «{name}»: условия участия "
            "и актуальные сведения от ArtFlow."
        )

    details: list[str] = []
    if source.get("event_date"):
        visible_date = plain_text(competition.get("event_date"))
        if visible_date:
            details.append(f"Дата: {visible_date}")
    city = plain_text(source.get("city"))
    if city:
        details.append(f"город: {city}")

    value = description
    if details:
        value = f"{value.rstrip('.')} — {', '.join(details)}."
    return meta_description(value)


def website_structured_data(
    *,
    base_url: str | None,
    description: str,
    site_content: dict[str, Any],
) -> list[dict[str, Any]]:
    if not base_url:
        return []

    home_url = f"{base_url}/"
    organization_id = f"{base_url}/#organization"
    organization: dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "Organization",
        "@id": organization_id,
        "name": SITE_NAME,
        "url": home_url,
        "logo": {
            "@type": "ImageObject",
            "url": f"{base_url}{DEFAULT_IMAGE_PATH}",
        },
    }
    instagram_url = (
        site_content.get("contacts", {}).get("instagram", {}).get("url")
    )
    if isinstance(instagram_url, str) and instagram_url.startswith("https://"):
        organization["sameAs"] = [instagram_url]

    website = {
        "@context": "https://schema.org",
        "@type": "WebSite",
        "@id": f"{base_url}/#website",
        "url": home_url,
        "name": SITE_NAME,
        "description": meta_description(description),
        "inLanguage": SITE_LANGUAGE,
        "publisher": {"@id": organization_id},
    }
    return [website, organization]


def breadcrumb_structured_data(
    items: list[tuple[str, str]],
    *,
    base_url: str | None,
) -> dict[str, Any] | None:
    if not base_url or not items:
        return None

    return {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {
                "@type": "ListItem",
                "position": position,
                "name": plain_text(name),
                "item": f"{base_url}{path}",
            }
            for position, (name, path) in enumerate(items, start=1)
        ],
    }


def competition_structured_data(
    competition: dict[str, Any],
    *,
    base_url: str | None,
    canonical_url: str | None,
    image_url: str | None,
) -> list[dict[str, Any]]:
    if not base_url or not canonical_url:
        return []

    display_name = plain_text(competition.get("name")) or "Конкурс ArtFlow"
    breadcrumb = breadcrumb_structured_data(
        [
            ("Главная", "/"),
            ("Конкурсы", "/competitions"),
            (display_name, canonical_url.removeprefix(base_url)),
        ],
        base_url=base_url,
    )
    if breadcrumb is None:
        return []

    source = competition.get("seo_source")
    source = source if isinstance(source, dict) else {}
    name = plain_text(source.get("name"))
    description = plain_text(source.get("description"))
    start_date = _iso_date(source.get("event_date"))
    city = plain_text(source.get("city"))
    place = plain_text(source.get("place"))
    if not name or not description or not start_date or not (city or place):
        return [breadcrumb]

    location_name = ", ".join(dict.fromkeys(item for item in (place, city) if item))
    location: dict[str, Any] = {
        "@type": "Place",
        "name": location_name,
    }
    if city:
        location["address"] = {
            "@type": "PostalAddress",
            "addressLocality": city,
        }

    event: dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "Event",
        "name": name,
        "description": meta_description(description),
        "startDate": start_date,
        "url": canonical_url,
        "location": location,

    }
    if image_url and image_url.startswith("https://"):
        event["image"] = [image_url]
    return [breadcrumb, event]


def _iso_date(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        return None
