from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import re
import socket
import sys
import unicodedata
# XML input is size-bounded and rejects DTD/entity/include declarations.
import xml.etree.ElementTree as ET  # nosec B405
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


_COMPETITION_PATH = re.compile(r"^/competitions/([1-9][0-9]*)$")
_TELEGRAM_DEEP_LINK = re.compile(
    r"^https://t\.me/[A-Za-z0-9_]+\?start=competition_([1-9][0-9]*)$"
)
_TRACEBACK_MARKERS = (
    "Traceback (most recent call last)",
    "starlette.middleware.errors",
    "uvicorn.protocols.http",
)
_FULL_SECURITY_HEADERS = (
    "content-security-policy",
    "referrer-policy",
    "x-frame-options",
    "permissions-policy",
)
_MINIMUM_HSTS_MAX_AGE = 31_536_000
_HSTS_FLAG_DIRECTIVES = {"includesubdomains", "preload"}
_MAX_RESPONSE_BYTES = 2_000_000
_DEFAULT_MAX_REQUESTS = 80
_MAX_REDIRECTS = 2
_REPORT_LEVELS = ("PASS", "WARNING", "FAIL", "NOT CHECKED")
_HTML_CONTENT_TYPES = ("text/html", "application/xhtml+xml")
_NORMAL_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 Chrome/126.0 Safari/537.36"
)
_GOOGLEBOT_USER_AGENT = (
    "Mozilla/5.0 (compatible; Googlebot/2.1; "
    "+http://www.google.com/bot.html)"
)
_YANDEXBOT_USER_AGENT = (
    "Mozilla/5.0 (compatible; YandexBot/3.0; "
    "+http://yandex.com/bots)"
)
_INDEXABLE_STATIC_PATHS = (
    "/",
    "/competitions",
    "/faq",
    "/about",
    "/how-to-participate",
)
_FORBIDDEN_EVENT_FIELDS = {
    "aggregateRating",
    "endDate",
    "eventAttendanceMode",
    "eventStatus",
    "offers",
    "organizer",
    "performer",
    "review",
}
_SAFE_REPORT_HEADERS = (
    "cache-control",
    "content-encoding",
    "content-type",
    "strict-transport-security",
    "x-content-type-options",
    "x-robots-tag",
)


class VerificationError(RuntimeError):
    pass


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@dataclass(frozen=True, slots=True)
class HttpResponse:
    status: int
    headers: dict[str, str]
    body: bytes
    requested_url: str = ""
    final_url: str = ""
    redirect_chain: tuple[str, ...] = ()

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")


class _HtmlAuditParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.elements: list[tuple[str, dict[str, str]]] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        self.elements.append(
            (
                tag.casefold(),
                {
                    name.casefold(): value or ""
                    for name, value in attrs
                },
            )
        )



@dataclass(frozen=True, slots=True)
class AuditFinding:
    level: str
    check: str
    message: str
    url: str | None = None

    def as_dict(self) -> dict[str, str]:
        result = {
            "level": self.level,
            "check": self.check,
            "message": self.message,
        }
        if self.url:
            result["url"] = self.url
        return result


@dataclass(slots=True)
class HtmlDocument:
    title: str
    meta: dict[str, list[str]]
    canonical_urls: list[str]
    icon_urls: list[str]
    hreflang_links: list[dict[str, str]]
    h1: list[str]
    main_text: str
    visible_text: str
    json_ld_sources: list[str]
    anchors: list[dict[str, Any]]
    breadcrumbs: list[str]
    element_ids: set[str]
    elements: list[tuple[str, dict[str, str]]]


def _normalize_text(value: str) -> str:
    return " ".join(value.split())


class _SeoHtmlParser(HTMLParser):
    _VOID_TAGS = {
        "area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "param", "source", "track", "wbr",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.elements: list[tuple[str, dict[str, str]]] = []
        self.meta: dict[str, list[str]] = {}
        self.canonical_urls: list[str] = []
        self.icon_urls: list[str] = []
        self.hreflang_links: list[dict[str, str]] = []
        self.h1_parts: list[list[str]] = []
        self.title_parts: list[str] = []
        self.main_parts: list[str] = []
        self.visible_parts: list[str] = []
        self.json_ld_parts: list[list[str]] = []
        self.anchors: list[dict[str, Any]] = []
        self.breadcrumb_parts: list[list[str]] = []
        self.element_ids: set[str] = set()
        self._stack: list[dict[str, Any]] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        normalized_tag = tag.casefold()
        normalized_attrs = {
            name.casefold(): value or ""
            for name, value in attrs
        }
        self.elements.append((normalized_tag, normalized_attrs))
        element_id = normalized_attrs.get("id")
        if element_id:
            self.element_ids.add(element_id)

        if normalized_tag == "meta":
            key = (
                normalized_attrs.get("name")
                or normalized_attrs.get("property")
                or ""
            ).casefold()
            if key:
                self.meta.setdefault(key, []).append(
                    normalized_attrs.get("content", "").strip()
                )
        elif normalized_tag == "link":
            rel = set(normalized_attrs.get("rel", "").casefold().split())
            href = normalized_attrs.get("href", "").strip()
            if "canonical" in rel:
                self.canonical_urls.append(href)
            if "icon" in rel:
                self.icon_urls.append(href)
            if normalized_attrs.get("hreflang"):
                self.hreflang_links.append(normalized_attrs)

        if normalized_tag == "img" and normalized_attrs.get("alt"):
            anchor_index = self._active_index("anchor_index")
            if anchor_index is not None:
                self.anchors[anchor_index]["text_parts"].append(
                    normalized_attrs["alt"]
                )
        if normalized_tag in self._VOID_TAGS:
            return

        entry: dict[str, Any] = {"tag": normalized_tag}
        if normalized_tag == "h1":
            self.h1_parts.append([])
            entry["h1_index"] = len(self.h1_parts) - 1
        if normalized_tag == "script" and (
            normalized_attrs.get("type", "").casefold()
            == "application/ld+json"
        ):
            self.json_ld_parts.append([])
            entry["json_ld_index"] = len(self.json_ld_parts) - 1
        if normalized_tag == "a":
            anchor = dict(normalized_attrs)
            anchor["text_parts"] = []
            self.anchors.append(anchor)
            entry["anchor_index"] = len(self.anchors) - 1

        parent_breadcrumb = any(
            item.get("breadcrumb_nav") for item in self._stack
        )
        class_names = set(normalized_attrs.get("class", "").casefold().split())
        aria_label = normalized_attrs.get("aria-label", "").casefold()
        entry["breadcrumb_nav"] = parent_breadcrumb or (
            normalized_tag == "nav"
            and ("breadcrumbs" in class_names or "\u0445\u043b\u0435\u0431\u043d" in aria_label)
        )
        if normalized_tag == "li" and entry["breadcrumb_nav"]:
            self.breadcrumb_parts.append([])
            entry["breadcrumb_index"] = len(self.breadcrumb_parts) - 1
        self._stack.append(entry)

    def handle_startendtag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        self.handle_starttag(tag, attrs)
        if tag.casefold() not in self._VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        normalized_tag = tag.casefold()
        for index in range(len(self._stack) - 1, -1, -1):
            if self._stack[index]["tag"] == normalized_tag:
                del self._stack[index:]
                return

    def handle_data(self, data: str) -> None:
        if not data.strip():
            return
        open_tags = {item["tag"] for item in self._stack}
        if "title" in open_tags:
            self.title_parts.append(data)
        h1_index = self._active_index("h1_index")
        if h1_index is not None:
            self.h1_parts[h1_index].append(data)
        json_ld_index = self._active_index("json_ld_index")
        if json_ld_index is not None:
            self.json_ld_parts[json_ld_index].append(data)
        anchor_index = self._active_index("anchor_index")
        if anchor_index is not None:
            self.anchors[anchor_index]["text_parts"].append(data)
        breadcrumb_index = self._active_index("breadcrumb_index")
        if breadcrumb_index is not None:
            self.breadcrumb_parts[breadcrumb_index].append(data)
        if "main" in open_tags:
            self.main_parts.append(data)
        if not open_tags.intersection({"script", "style", "template"}):
            self.visible_parts.append(data)

    def _active_index(self, name: str) -> int | None:
        for item in reversed(self._stack):
            if name in item:
                return int(item[name])
        return None

    def document(self) -> HtmlDocument:
        anchors: list[dict[str, Any]] = []
        for item in self.anchors:
            anchor = dict(item)
            anchor["text"] = _normalize_text(
                " ".join(anchor.pop("text_parts"))
            )
            anchors.append(anchor)
        return HtmlDocument(
            title=_normalize_text(" ".join(self.title_parts)),
            meta=self.meta,
            canonical_urls=self.canonical_urls,
            icon_urls=self.icon_urls,
            hreflang_links=self.hreflang_links,
            h1=[_normalize_text(" ".join(parts)) for parts in self.h1_parts],
            main_text=_normalize_text(" ".join(self.main_parts)),
            visible_text=_normalize_text(" ".join(self.visible_parts)),
            json_ld_sources=[
                "".join(parts).strip() for parts in self.json_ld_parts
            ],
            anchors=anchors,
            breadcrumbs=[
                _normalize_text(" ".join(parts))
                for parts in self.breadcrumb_parts
                if _normalize_text(" ".join(parts))
            ],
            element_ids=self.element_ids,
            elements=self.elements,
        )


def parse_html_document(html: str) -> HtmlDocument:
    parser = _SeoHtmlParser()
    parser.feed(html)
    parser.close()
    return parser.document()


def _meta_value(document: HtmlDocument, name: str) -> str:
    values = document.meta.get(name.casefold(), [])
    return values[0] if values else ""


def parse_json_ld(document: HtmlDocument) -> tuple[list[Any], list[str]]:
    values: list[Any] = []
    errors: list[str] = []
    for index, source in enumerate(document.json_ld_sources, start=1):
        try:
            values.append(json.loads(source))
        except json.JSONDecodeError as exc:
            errors.append(f"JSON-LD block {index} is invalid: {exc.msg}")
    return values, errors


def _schema_nodes(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, list):
        for item in value:
            yield from _schema_nodes(item)
    elif isinstance(value, dict):
        yield value
        graph = value.get("@graph")
        if graph is not None:
            yield from _schema_nodes(graph)


def schema_type_names(values: Iterable[Any]) -> list[str]:
    names: list[str] = []
    for value in values:
        for node in _schema_nodes(value):
            node_type = node.get("@type")
            if isinstance(node_type, str):
                names.append(node_type)
            elif isinstance(node_type, list):
                names.extend(
                    item for item in node_type if isinstance(item, str)
                )
    return sorted(set(names))


def _safe_xml_root(xml_body: bytes) -> ET.Element:
    if len(xml_body) > _MAX_RESPONSE_BYTES:
        raise VerificationError("XML exceeds the 2 MB verification limit")
    lowered = xml_body.lower()
    forbidden_declarations = (
        b"<!doctype",
        b"<!entity",
        b"<!attlist",
        b"<!notation",
        b"<xi:include",
    )
    if any(item in lowered for item in forbidden_declarations):
        raise VerificationError("XML contains a forbidden DTD, entity, or include")
    return ET.fromstring(xml_body)  # nosec B314


def parse_sitemap(xml_body: bytes, *, expected_origin: str) -> list[str]:
    try:
        root = _safe_xml_root(xml_body)
    except ET.ParseError as exc:
        raise VerificationError(f"sitemap.xml is not valid XML: {exc}") from exc
    if root.tag.rsplit("}", 1)[-1] != "urlset":
        raise VerificationError("sitemap.xml root must be urlset")

    urls: list[str] = []
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] != "loc" or not element.text:
            continue
        url = element.text.strip()
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or f"{parsed.scheme}://{parsed.netloc}" != expected_origin
            or parsed.query
            or parsed.fragment
        ):
            raise VerificationError(
                f"sitemap.xml contains a non-canonical URL: {url}"
            )
        urls.append(url)
    if not urls:
        raise VerificationError("sitemap.xml has no URL entries")
    return urls


def soft_404_reasons(status: int, document: HtmlDocument) -> list[str]:
    if status != 200:
        return []
    lead_text = " ".join([document.title, *document.h1]).casefold()
    markers = ("404", "\u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d", "\u0441\u0442\u0440\u0430\u043d\u0438\u0446\u0430 \u043e\u0442\u0441\u0443\u0442\u0441\u0442\u0432\u0443\u0435\u0442", "page not found")
    return [
        f"200 response looks like a missing page ({marker})"
        for marker in markers
        if marker in lead_text
    ]


def canonical_errors(
    document: HtmlDocument,
    *,
    expected_url: str,
    indexable: bool,
) -> list[str]:
    robots = _meta_value(document, "robots").casefold()
    errors: list[str] = []
    if not indexable:
        if document.canonical_urls:
            errors.append("non-indexable page exposes canonical")
        if "noindex" not in robots:
            errors.append("non-indexable page lacks noindex")
        return errors

    if len(document.canonical_urls) != 1:
        errors.append("indexable page must have exactly one canonical")
    elif document.canonical_urls[0] != expected_url:
        errors.append(
            f"canonical is {document.canonical_urls[0]!r}, "
            f"expected {expected_url!r}"
        )
    if "noindex" in robots or "index" not in robots:
        errors.append("indexable page has unexpected robots directives")
    return errors


def json_ld_errors(
    document: HtmlDocument,
    *,
    page_url: str,
    page_kind: str,
) -> tuple[list[str], list[str]]:
    values, errors = parse_json_ld(document)
    types = schema_type_names(values)
    nodes = [node for value in values for node in _schema_nodes(value)]

    for node in nodes:
        context = node.get("@context")
        if context is not None and context not in {
            "https://schema.org",
            "http://schema.org",
        }:
            errors.append(f"unexpected JSON-LD @context {context!r}")

    if page_kind == "home":
        for required_type in ("WebSite", "Organization"):
            if required_type not in types:
                errors.append(f"home JSON-LD lacks {required_type}")

    event_nodes = [node for node in nodes if node.get("@type") == "Event"]
    if page_kind == "competition":
        if "BreadcrumbList" not in types:
            errors.append("competition JSON-LD lacks BreadcrumbList")
        if not event_nodes:
            errors.append("competition JSON-LD lacks Event")
    for event in event_nodes:
        for required_field in (
            "name", "description", "startDate", "location", "url",
        ):
            if not event.get(required_field):
                errors.append(f"Event lacks {required_field}")
        if event.get("url") != page_url:
            errors.append("Event url does not match canonical")
        visible_text = document.main_text.casefold()
        event_description = _normalize_text(str(event.get("description", "")))
        if event_description and event_description.casefold() not in visible_text:
            errors.append("Event description is not present in visible content")
        raw_start_date = event.get("startDate")
        if isinstance(raw_start_date, str):
            try:
                display_date = datetime.fromisoformat(
                    raw_start_date.replace("Z", "+00:00")
                ).strftime("%d.%m.%Y")
            except ValueError:
                errors.append("Event startDate is malformed")
            else:
                if (
                    raw_start_date.casefold() not in visible_text
                    and display_date.casefold() not in visible_text
                ):
                    errors.append("Event startDate is not present in visible content")
        location = event.get("location")
        if isinstance(location, dict):
            location_values = [location.get("name")]
            address = location.get("address")
            if isinstance(address, dict):
                location_values.append(address.get("addressLocality"))
            for value in location_values:
                if not isinstance(value, str):
                    continue
                for fragment in value.split(","):
                    normalized_fragment = _normalize_text(fragment).casefold()
                    if normalized_fragment and normalized_fragment not in visible_text:
                        errors.append(
                            f"Event location value is not visible: {fragment.strip()!r}"
                        )
        forbidden = sorted(_FORBIDDEN_EVENT_FIELDS.intersection(event))
        if forbidden:
            errors.append(
                "Event contains unverified fields: " + ", ".join(forbidden)
            )
        images = event.get("image")
        if isinstance(images, str):
            images = [images]
        if isinstance(images, list):
            for image in images:
                if not isinstance(image, str) or not image.startswith("https://"):
                    errors.append("Event image must be an absolute HTTPS URL")

    breadcrumb_nodes = [
        node for node in nodes if node.get("@type") == "BreadcrumbList"
    ]
    if breadcrumb_nodes and document.breadcrumbs:
        items = breadcrumb_nodes[0].get("itemListElement")
        if isinstance(items, list):
            schema_labels = [
                str(item.get("name", "")).strip()
                for item in items
                if isinstance(item, dict)
            ]
            if schema_labels != document.breadcrumbs:
                errors.append(
                    "BreadcrumbList labels differ from visible breadcrumbs"
                )
    if page_kind == "competition" and not event_nodes:
        errors = [
            error for error in errors
            if error != "competition JSON-LD lacks Event"
        ]
    return errors, types

def validate_public_base_url(value: str) -> str:
    if any(unicodedata.category(character) == "Cc" for character in value):
        raise VerificationError("BASE_URL contains control characters")
    try:
        parsed = urlsplit(value.strip())
        port = parsed.port
    except ValueError as exc:
        raise VerificationError("BASE_URL is malformed") from exc
    if (
        parsed.scheme.casefold() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or port not in {None, 443}
        or any(character.isspace() for character in parsed.hostname)
    ):
        raise VerificationError("BASE_URL must be an HTTPS origin on port 443")
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        if parsed.hostname.casefold() == "localhost":
            raise VerificationError("BASE_URL must be public")
    else:
        if address.is_loopback or address.is_unspecified or address.is_private:
            raise VerificationError("BASE_URL must be public")
    return value.strip().rstrip("/")


def _safe_read(response) -> bytes:
    body = response.read(_MAX_RESPONSE_BYTES + 1)
    if len(body) > _MAX_RESPONSE_BYTES:
        raise VerificationError("Response exceeds the 2 MB verification limit")
    return body


class ProductionFetcher:
    def __init__(
        self,
        base_url: str,
        *,
        timeout: float,
        max_requests: int = _DEFAULT_MAX_REQUESTS,
        allowed_hostnames: Iterable[str] = (),
    ) -> None:
        self.base_url = validate_public_base_url(base_url)
        self.timeout = max(1.0, min(timeout, 30.0))
        self.max_requests = max(1, min(max_requests, 200))
        self.request_count = 0
        self.opener = build_opener(_NoRedirectHandler())
        base_hostname = urlsplit(self.base_url).hostname or ""
        self.allowed_hostnames = {base_hostname.casefold()}
        for hostname in allowed_hostnames:
            self.register_hostname(hostname)

    def register_hostname(self, hostname: str) -> None:
        normalized = hostname.strip().rstrip(".").casefold()
        if (
            not normalized
            or "://" in normalized
            or "/" in normalized
            or "@" in normalized
            or any(character.isspace() for character in normalized)
        ):
            raise VerificationError(f"Invalid audit hostname: {hostname!r}")
        self.allowed_hostnames.add(normalized)

    def get(
        self,
        path: str,
        *,
        host: str | None = None,
        user_agent: str = "ArtFlowWeb-production-verifier/2.0",
        follow_redirects: bool = False,
        method: str = "GET",
    ) -> HttpResponse:
        if not path.startswith("/") or path.startswith("//"):
            raise VerificationError("Verifier only requests same-origin paths")
        url = urljoin(f"{self.base_url}/", path.lstrip("/"))
        return self.fetch_url(
            url,
            host=host,
            user_agent=user_agent,
            follow_redirects=follow_redirects,
            method=method,
        )

    def fetch_url(
        self,
        url: str,
        *,
        host: str | None = None,
        user_agent: str = "ArtFlowWeb-production-verifier/2.0",
        follow_redirects: bool = True,
        method: str = "GET",
        max_redirects: int = _MAX_REDIRECTS,
    ) -> HttpResponse:
        normalized_method = method.upper()
        if normalized_method not in {"GET", "HEAD"}:
            raise VerificationError("Verifier only permits GET and HEAD")
        if any(unicodedata.category(character) == "Cc" for character in user_agent):
            raise VerificationError("User-Agent contains control characters")

        requested_url = self._validate_fetch_url(url)
        current_url = requested_url
        redirect_chain: list[str] = []
        while True:
            response = self._request_once(
                current_url,
                host=host,
                user_agent=user_agent,
                method=normalized_method,
            )
            is_redirect = response.status in {301, 302, 303, 307, 308}
            location = response.headers.get("location", "")
            if not follow_redirects or not is_redirect or not location:
                return HttpResponse(
                    status=response.status,
                    headers=response.headers,
                    body=response.body,
                    requested_url=requested_url,
                    final_url=current_url,
                    redirect_chain=tuple(redirect_chain),
                )
            if len(redirect_chain) >= max_redirects:
                raise VerificationError(
                    f"Redirect limit exceeded for {requested_url}"
                )
            next_url = self._validate_fetch_url(urljoin(current_url, location))
            if next_url in {requested_url, *redirect_chain}:
                raise VerificationError(
                    f"Redirect loop detected for {requested_url}"
                )
            redirect_chain.append(next_url)
            current_url = next_url
            host = None

    def _validate_fetch_url(self, value: str) -> str:
        if any(unicodedata.category(character) == "Cc" for character in value):
            raise VerificationError("Audit URL contains control characters")
        try:
            parsed = urlsplit(value)
            port = parsed.port
        except ValueError as exc:
            raise VerificationError("Audit URL is malformed") from exc
        if (
            parsed.scheme.casefold() not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
        ):
            raise VerificationError("Audit URL must be an HTTP(S) URL without credentials")
        expected_port = 443 if parsed.scheme.casefold() == "https" else 80
        if port not in {None, expected_port}:
            raise VerificationError("Audit URL uses a non-standard port")
        if parsed.hostname.casefold().rstrip(".") not in self.allowed_hostnames:
            raise VerificationError(
                f"Redirect left the approved audit host: {parsed.hostname}"
            )
        return urlunsplit(
            (
                parsed.scheme.casefold(),
                parsed.netloc,
                parsed.path or "/",
                parsed.query,
                "",
            )
        )

    def _request_once(
        self,
        url: str,
        *,
        host: str | None,
        user_agent: str,
        method: str,
    ) -> HttpResponse:
        if self.request_count >= self.max_requests:
            raise VerificationError(
                f"Request limit ({self.max_requests}) reached"
            )
        self.request_count += 1
        request = Request(
            url,
            method=method,
            headers={
                "Accept": (
                    "text/html,application/xhtml+xml,application/xml,"
                    "application/json,text/plain,image/*;q=0.9,*/*;q=0.8"
                ),
                "User-Agent": user_agent,
            },
        )
        if host is not None:
            request.add_unredirected_header("Host", host)
        try:
            response = self.opener.open(request, timeout=self.timeout)
        except HTTPError as exc:
            response = exc
        headers = {
            name.casefold(): value.strip()
            for name, value in response.headers.items()
        }
        body = b"" if method == "HEAD" else _safe_read(response)
        return HttpResponse(
            status=response.status,
            headers=headers,
            body=body,
            requested_url=url,
            final_url=url,
        )


def hsts_header_error(value: str | None) -> str | None:
    actual_value = "" if value is None else value

    def invalid(reason: str) -> str:
        return f"Invalid HSTS header {actual_value!r}: {reason}"

    if not actual_value.strip():
        return invalid("header is missing")

    max_age_values: list[str | None] = []
    for directive in actual_value.split(";"):
        directive = directive.strip()
        if not directive:
            continue

        name, separator, raw_value = directive.partition("=")
        normalized_name = name.strip().casefold()
        if normalized_name == "max-age":
            max_age_values.append(raw_value.strip() if separator else None)
            continue
        if normalized_name in _HSTS_FLAG_DIRECTIVES:
            if separator:
                return invalid(f"{name.strip()} must not have a value")
            continue
        return invalid(f"unsupported directive {name.strip()!r}")

    if not max_age_values:
        return invalid("max-age is missing")
    if len(max_age_values) != 1:
        return invalid("exactly one max-age directive is required")

    max_age_value = max_age_values[0]
    if max_age_value is None or re.fullmatch(r"[0-9]+", max_age_value) is None:
        return invalid("max-age must be an integer")
    if int(max_age_value) < _MINIMUM_HSTS_MAX_AGE:
        return invalid(f"max-age must be at least {_MINIMUM_HSTS_MAX_AGE}")
    return None


def security_header_errors(response: HttpResponse) -> list[str]:
    errors: list[str] = []
    if response.headers.get("x-content-type-options", "").casefold() != "nosniff":
        errors.append("X-Content-Type-Options must be nosniff")
    for name in _FULL_SECURITY_HEADERS:
        if not response.headers.get(name):
            errors.append(f"Missing {name}")

    csp = response.headers.get("content-security-policy", "")
    if "unsafe-inline" in csp or "unsafe-eval" in csp:
        errors.append("Public CSP contains an unsafe source")
    hsts_error = hsts_header_error(
        response.headers.get("strict-transport-security")
    )
    if hsts_error:
        errors.append(hsts_error)
    return errors


def _parsed_url_errors(url: str) -> list[str]:
    errors: list[str] = []
    if any(unicodedata.category(character) == "Cc" for character in url):
        return ["URL contains control characters"]
    try:
        parsed = urlsplit(url)
        parsed.port
    except ValueError:
        return ["URL is malformed"]
    if parsed.scheme.casefold() in {"javascript", "data"}:
        errors.append(f"Forbidden URL scheme: {parsed.scheme.casefold()}")
    if parsed.username is not None or parsed.password is not None:
        errors.append("URL contains user information")
    return errors


def audit_html(html: str, *, base_hostname: str) -> list[str]:
    parser = _HtmlAuditParser()
    parser.feed(html)
    errors: list[str] = []
    for tag, attrs in parser.elements:
        target = attrs.get("target", "").casefold()
        if tag == "a" and target == "_blank":
            rel = set(attrs.get("rel", "").casefold().split())
            if not {"noopener", "noreferrer"}.issubset(rel):
                errors.append("target=_blank link lacks noopener noreferrer")

        for attribute in ("href", "src"):
            url = attrs.get(attribute, "").strip()
            if not url:
                continue
            errors.extend(_parsed_url_errors(url))
            try:
                parsed = urlsplit(url)
                parsed.port
            except ValueError:
                continue
            scheme = parsed.scheme.casefold()
            hostname = (parsed.hostname or "").casefold()
            if parsed.netloc and not scheme:
                errors.append("Protocol-relative URL is forbidden")
                continue
            if scheme in {"http", "https"}:
                if not hostname:
                    errors.append("Absolute URL has no hostname")
                    continue
                if hostname != base_hostname.casefold() and scheme != "https":
                    errors.append("External URL is not HTTPS")
                if hostname in {"t.me", "wa.me", "api.whatsapp.com"} and scheme != "https":
                    errors.append("Social URL is not HTTPS")
                if "instagram" in hostname and hostname not in {
                    "instagram.com",
                    "www.instagram.com",
                }:
                    errors.append("Instagram link uses an unexpected host")
                if tag == "img" and hostname != base_hostname.casefold():
                    if attrs.get("referrerpolicy", "").casefold() != "no-referrer":
                        errors.append("External image lacks referrerpolicy=no-referrer")
            elif scheme == "mailto":
                address = parsed.path
                if address.count("@") != 1 or parsed.query or parsed.fragment:
                    errors.append("Malformed mailto link")
            elif scheme and scheme not in {"javascript", "data"}:
                errors.append(f"Unexpected URL scheme: {scheme}")
    return errors


def _competition_paths(html: str) -> list[str]:
    parser = _HtmlAuditParser()
    parser.feed(html)
    paths = {
        urlsplit(attrs.get("href", "")).path
        for tag, attrs in parser.elements
        if tag == "a" and _COMPETITION_PATH.fullmatch(
            urlsplit(attrs.get("href", "")).path
        )
    }
    return sorted(paths, key=lambda path: int(path.rsplit("/", 1)[1]))


def _deep_link_ids(html: str) -> set[int]:
    parser = _HtmlAuditParser()
    parser.feed(html)
    ids: set[int] = set()
    for tag, attrs in parser.elements:
        if tag != "a":
            continue
        match = _TELEGRAM_DEEP_LINK.fullmatch(attrs.get("href", ""))
        if match:
            ids.add(int(match.group(1)))
    return ids


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def _check_page(
    fetcher: ProductionFetcher,
    path: str,
    *,
    expected_status: int,
) -> HttpResponse:
    response = fetcher.get(path)
    _require(response.status == expected_status, f"{path} returned {response.status}")
    for marker in _TRACEBACK_MARKERS:
        _require(marker not in response.text, f"{path} exposes a server traceback")
    return response


def verify(base_url: str, *, timeout: float, competition_id: int | None) -> list[str]:
    fetcher = ProductionFetcher(base_url, timeout=timeout)
    base_hostname = urlsplit(fetcher.base_url).hostname or ""
    checks: list[str] = []

    health = _check_page(fetcher, "/health", expected_status=200)
    try:
        health_payload = json.loads(health.text)
    except json.JSONDecodeError as exc:
        raise VerificationError("/health did not return JSON") from exc
    _require(health_payload == {"status": "ok"}, "/health payload is unexpected")
    _require(not security_header_errors(health), "; ".join(security_header_errors(health)))
    checks.append("HTTPS health and security headers")

    html_responses: dict[str, HttpResponse] = {}
    for path in ("/", "/competitions", "/faq"):
        response = _check_page(fetcher, path, expected_status=200)
        errors = security_header_errors(response)
        errors.extend(audit_html(response.text, base_hostname=base_hostname))
        _require(not errors, f"{path}: {'; '.join(errors)}")
        html_responses[path] = response
    checks.append("Public HTML pages and external-link policy")

    for path in ("/docs", "/redoc", "/openapi.json"):
        _check_page(fetcher, path, expected_status=404)
    checks.append("Production API documentation is disabled")

    missing = _check_page(
        fetcher,
        "/__artflow_verification_missing__",
        expected_status=404,
    )
    _require(not security_header_errors(missing), "; ".join(security_header_errors(missing)))
    checks.append("Safe 404 response")

    robots = _check_page(fetcher, "/robots.txt", expected_status=200)
    _require("User-agent:" in robots.text, "/robots.txt has no User-agent directive")
    _require(
        robots.headers.get("x-content-type-options", "").casefold() == "nosniff",
        "/robots.txt lacks nosniff",
    )
    checks.append("robots.txt")

    static_asset = _check_page(fetcher, "/static/css/base.css", expected_status=200)
    _require(
        static_asset.headers.get("x-content-type-options", "").casefold() == "nosniff",
        "Static CSS lacks nosniff",
    )
    checks.append("Static asset nosniff")

    unknown_host = fetcher.get("/health", host="invalid.artflow-verifier.invalid")
    _require(
        unknown_host.status in {400, 403, 404, 421},
        f"Unknown Host was not rejected; received {unknown_host.status}",
    )
    checks.append("Unknown Host rejection")

    detail_paths = _competition_paths(html_responses["/competitions"].text)
    if competition_id is not None:
        requested_path = f"/competitions/{competition_id}"
        detail_paths = [requested_path, *(
            path for path in detail_paths if path != requested_path
        )]
    _require(detail_paths, "No published competition links were found")

    deep_link_found = False
    for path in detail_paths[:20]:
        response = _check_page(fetcher, path, expected_status=200)
        errors = security_header_errors(response)
        errors.extend(audit_html(response.text, base_hostname=base_hostname))
        _require(not errors, f"{path}: {'; '.join(errors)}")
        expected_id = int(path.rsplit("/", 1)[1])
        if expected_id in _deep_link_ids(response.text):
            deep_link_found = True
            break
    _require(deep_link_found, "No valid competition_{id} Telegram deep link was found")
    checks.append("Telegram competition_{id} deep link")
    return checks



def _add_finding(
    findings: list[AuditFinding],
    level: str,
    check: str,
    message: str,
    url: str | None = None,
) -> None:
    if level not in _REPORT_LEVELS:
        raise ValueError(f"Unknown audit level: {level}")
    findings.append(AuditFinding(level, check, message, url))


def _safe_response_headers(response: HttpResponse) -> dict[str, str]:
    return {
        name: response.headers[name]
        for name in _SAFE_REPORT_HEADERS
        if name in response.headers
    }


def _response_record(response: HttpResponse) -> dict[str, Any]:
    return {
        "requested_url": response.requested_url,
        "final_url": response.final_url,
        "redirect_chain": list(response.redirect_chain),
        "status": response.status,
        "headers": _safe_response_headers(response),
        "body_bytes": len(response.body),
    }


def _exception_message(exc: BaseException) -> str:
    message = _normalize_text(str(exc))
    return message[:300] if message else exc.__class__.__name__


def _fetch_for_audit(
    fetcher: ProductionFetcher,
    findings: list[AuditFinding],
    url: str,
    *,
    check: str,
    follow_redirects: bool = False,
    user_agent: str = _NORMAL_USER_AGENT,
    method: str = "GET",
) -> HttpResponse | None:
    try:
        return fetcher.fetch_url(
            url,
            follow_redirects=follow_redirects,
            user_agent=user_agent,
            method=method,
        )
    except (VerificationError, URLError, socket.timeout) as exc:
        _add_finding(
            findings,
            "FAIL",
            check,
            f"Request failed: {_exception_message(exc)}",
            url,
        )
        return None


def _page_kind(path: str) -> str:
    if path == "/":
        return "home"
    if _COMPETITION_PATH.fullmatch(path):
        return "competition"
    return "static"


def _html_snapshot(
    response: HttpResponse,
    *,
    expected_url: str,
    base_hostname: str,
    findings: list[AuditFinding],
) -> tuple[HtmlDocument, dict[str, Any]]:
    document = parse_html_document(response.text)
    parsed_url = urlsplit(expected_url)
    page_kind = _page_kind(parsed_url.path)
    errors: list[str] = []
    if response.status != 200:
        errors.append(f"returned HTTP {response.status}")
    content_type = response.headers.get("content-type", "").casefold()
    if not any(value in content_type for value in _HTML_CONTENT_TYPES):
        errors.append(f"unexpected Content-Type {content_type!r}")
    errors.extend(security_header_errors(response))
    errors.extend(audit_html(response.text, base_hostname=base_hostname))
    errors.extend(
        canonical_errors(
            document,
            expected_url=expected_url,
            indexable=True,
        )
    )
    errors.extend(soft_404_reasons(response.status, document))
    if not document.title:
        errors.append("title is empty")
    if len(document.h1) != 1 or not document.h1[0]:
        errors.append("page must contain exactly one non-empty H1")
    description = _meta_value(document, "description")
    if not description:
        errors.append("meta description is empty")
    for field in (
        "og:type",
        "og:title",
        "og:description",
        "og:site_name",
        "og:url",
        "og:image",
        "twitter:card",
        "twitter:title",
        "twitter:description",
        "twitter:image",
    ):
        if not _meta_value(document, field):
            errors.append(f"{field} is empty")
    if _meta_value(document, "og:url") != expected_url:
        errors.append("og:url does not match canonical")
    if _meta_value(document, "og:site_name") != "ArtFlow":
        errors.append("og:site_name does not identify ArtFlow")
    for image_field in ("og:image", "twitter:image"):
        image_url = _meta_value(document, image_field)
        if image_url and not image_url.startswith("https://"):
            errors.append(f"{image_field} is not an absolute HTTPS URL")

    raw_html = response.text
    for marker in _TRACEBACK_MARKERS:
        if marker in raw_html:
            errors.append("server traceback marker is exposed")
    if re.search(r"[A-Za-z]:\\", raw_html):
        errors.append("HTML exposes a local Windows path")
    for marker in ("localhost", "127.0.0.1", ".up.railway.app"):
        if marker.casefold() in raw_html.casefold():
            errors.append(f"HTML exposes forbidden infrastructure marker {marker}")

    structured_errors, schema_types = json_ld_errors(
        document,
        page_url=expected_url,
        page_kind=page_kind,
    )
    if page_kind == "competition" and "Event" not in schema_types:
        structured_errors = [
            error for error in structured_errors
            if error != "competition JSON-LD lacks Event"
        ]
    errors.extend(structured_errors)
    if page_kind == "static" and parsed_url.path != "/competitions":
        if "BreadcrumbList" not in schema_types:
            errors.append("internal static page lacks BreadcrumbList")
    if page_kind == "competition" and "Event" not in schema_types:
        _add_finding(
            findings,
            "WARNING",
            "json-ld",
            (
                "Event is omitted. This is correct only when required factual "
                "event fields are incomplete."
            ),
            expected_url,
        )

    values, _ = parse_json_ld(document)
    event_nodes = [
        node
        for value in values
        for node in _schema_nodes(value)
        if node.get("@type") == "Event"
    ]
    if event_nodes and document.h1:
        event_name = _normalize_text(str(event_nodes[0].get("name", "")))
        if event_name != document.h1[0]:
            errors.append("Event name differs from page H1")

    for error in sorted(set(errors)):
        _add_finding(
            findings, "FAIL", "indexable-page", error, expected_url
        )
    if not errors:
        _add_finding(
            findings,
            "PASS",
            "indexable-page",
            "HTTP, canonical, robots, metadata and schema checks passed",
            expected_url,
        )

    title_length = len(document.title)
    description_length = len(description)
    if title_length < 25 or title_length > 70:
        _add_finding(
            findings,
            "WARNING",
            "snippet",
            f"title length is {title_length}; review the search snippet",
            expected_url,
        )
    if description_length < 70 or description_length > 180:
        _add_finding(
            findings,
            "WARNING",
            "snippet",
            (
                f"meta description length is {description_length}; "
                "review the search snippet"
            ),
            expected_url,
        )

    summary = {
        "url": expected_url,
        "status": response.status,
        "title": document.title,
        "title_length": title_length,
        "description": description,
        "description_length": description_length,
        "h1": document.h1,
        "canonical": document.canonical_urls,
        "robots": _meta_value(document, "robots"),
        "og_title": _meta_value(document, "og:title"),
        "og_description": _meta_value(document, "og:description"),
        "og_image": _meta_value(document, "og:image"),
        "og_url": _meta_value(document, "og:url"),
        "schema_types": schema_types,
        "headers": _safe_response_headers(response),
    }
    return document, summary


def _audit_missing_response(
    response: HttpResponse,
    *,
    expected_url: str,
    findings: list[AuditFinding],
    html_expected: bool,
) -> None:
    errors: list[str] = []
    if response.status != 404:
        errors.append(f"expected HTTP 404, received {response.status}")
    if response.headers.get("x-content-type-options", "").casefold() != "nosniff":
        errors.append("missing response lacks nosniff")
    for marker in _TRACEBACK_MARKERS:
        if marker in response.text:
            errors.append("missing response exposes a traceback")
    content_type = response.headers.get("content-type", "").casefold()
    if html_expected or "text/html" in content_type:
        document = parse_html_document(response.text)
        errors.extend(
            canonical_errors(
                document,
                expected_url=expected_url,
                indexable=False,
            )
        )
    for error in errors:
        _add_finding(findings, "FAIL", "real-404", error, expected_url)
    if not errors:
        _add_finding(
            findings,
            "PASS",
            "real-404",
            "Real 404 without canonical, indexability or traceback",
            expected_url,
        )


def _canonical_link_target(base_url: str, href: str) -> tuple[str, str] | None:
    value = href.strip()
    if not value or value == "#":
        return None
    try:
        parsed = urlsplit(urljoin(f"{base_url}/", value))
        port = parsed.port
    except ValueError:
        return None
    base = urlsplit(base_url)
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname != base.hostname
        or port not in {None, 443}
    ):
        return None
    target_url = urlunsplit(("https", base.netloc, parsed.path or "/", "", ""))
    return target_url, parsed.fragment


def _audit_internal_graph(
    *,
    base_url: str,
    documents: dict[str, HtmlDocument],
    responses: dict[str, HttpResponse],
    sitemap_urls: list[str],
    findings: list[AuditFinding],
) -> dict[str, Any]:
    inbound: dict[str, set[str]] = {url: set() for url in sitemap_urls}
    broken: list[dict[str, str]] = []
    empty_links: list[dict[str, str]] = []
    discovered: set[str] = set()

    for source_url, document in documents.items():
        for anchor in document.anchors:
            href = str(anchor.get("href", "")).strip()
            accessible_name = (
                str(anchor.get("aria-label", "")).strip()
                or str(anchor.get("text", "")).strip()
            )
            if not href or href == "#":
                empty_links.append({"source": source_url, "href": href})
                _add_finding(
                    findings,
                    "FAIL",
                    "internal-links",
                    "empty or placeholder link",
                    source_url,
                )
                continue
            if not accessible_name:
                _add_finding(
                    findings,
                    "FAIL",
                    "internal-links",
                    f"link {href!r} has no accessible text",
                    source_url,
                )
            target = _canonical_link_target(base_url, href)
            if target is None:
                continue
            target_url, fragment = target
            if target_url.startswith(f"{base_url}/static/"):
                continue
            discovered.add(target_url)
            if target_url in inbound and target_url != source_url:
                inbound[target_url].add(source_url)
            target_response = responses.get(target_url)
            if target_response is None:
                broken.append({"source": source_url, "target": target_url})
                _add_finding(
                    findings,
                    "FAIL",
                    "internal-links",
                    f"internal target was not audited: {target_url}",
                    source_url,
                )
            elif target_response.status != 200:
                broken.append({"source": source_url, "target": target_url})
                _add_finding(
                    findings,
                    "FAIL",
                    "internal-links",
                    f"internal target returned {target_response.status}: {target_url}",
                    source_url,
                )
            if fragment and target_url in documents:
                if fragment not in documents[target_url].element_ids:
                    target_with_fragment = f"{target_url}#{fragment}"
                    broken.append({
                        "source": source_url,
                        "target": target_with_fragment,
                    })
                    _add_finding(
                        findings,
                        "FAIL",
                        "internal-links",
                        f"fragment target does not exist: #{fragment}",
                        source_url,
                    )

    orphans = [
        url
        for url in sitemap_urls
        if url != f"{base_url}/" and not inbound.get(url)
    ]
    for url in orphans:
        _add_finding(
            findings,
            "FAIL",
            "orphan-pages",
            "Sitemap URL has no internal inbound link",
            url,
        )
    if not broken and not empty_links and not orphans:
        _add_finding(
            findings,
            "PASS",
            "internal-links",
            "No broken links, placeholder links or sitemap orphans found",
            base_url,
        )
    return {
        "discovered_internal_urls": sorted(discovered),
        "broken": broken,
        "empty_or_placeholder": empty_links,
        "orphans": orphans,
        "inbound_counts": {
            url: len(sources) for url, sources in sorted(inbound.items())
        },
    }


def _bot_signature(response: HttpResponse) -> dict[str, Any]:
    document = parse_html_document(response.text)
    values, json_errors = parse_json_ld(document)
    return {
        "status": response.status,
        "canonical": document.canonical_urls,
        "robots": _meta_value(document, "robots"),
        "title": document.title,
        "h1": document.h1,
        "main_text_sha256": hashlib.sha256(
            document.main_text.encode("utf-8")
        ).hexdigest(),
        "schema_types": schema_type_names(values),
        "json_ld_errors": json_errors,
    }


def _markdown_cell(value: Any) -> str:
    return _normalize_text(str(value)).replace("|", "\\|")


def render_markdown_report(report: dict[str, Any]) -> str:
    lines = [
        "# ArtFlow production SEO audit",
        "",
        f"- Generated: {report['generated_at']}",
        f"- Base URL: {report['base_url']}",
        f"- Overall: **{report['overall']}**",
        f"- Requests: {report['request_count']} / {report['max_requests']}",
        "",
        "## Summary",
        "",
    ]
    for level in _REPORT_LEVELS:
        lines.append(f"- {level}: {report['summary'].get(level, 0)}")

    lines.extend([
        "",
        "## Domain Matrix",
        "",
        "| Requested | Status | Redirects | Final | Result |",
        "|---|---:|---:|---|---|",
    ])
    for row in report.get("domain_matrix", []):
        lines.append(
            "| {requested} | {status} | {redirects} | {final} | {result} |".format(
                requested=_markdown_cell(row.get("requested_url", "")),
                status=_markdown_cell(row.get("status", "")),
                redirects=len(row.get("redirect_chain", [])),
                final=_markdown_cell(row.get("final_url", "")),
                result=_markdown_cell(row.get("result", "")),
            )
        )

    lines.extend([
        "",
        "## Snippet QA",
        "",
        "| URL | Title | Description | H1 | Canonical | Schema |",
        "|---|---:|---:|---:|---|---|",
    ])
    for page in report.get("pages", []):
        lines.append(
            "| {url} | {title} | {description} | {h1} | {canonical} | {schema} |".format(
                url=_markdown_cell(page["url"]),
                title=page["title_length"],
                description=page["description_length"],
                h1=len(page["h1"]),
                canonical=_markdown_cell(", ".join(page["canonical"])),
                schema=_markdown_cell(", ".join(page["schema_types"])),
            )
        )

    lines.extend(["", "## Findings", ""])
    for finding in report.get("findings", []):
        location = f" ({finding['url']})" if finding.get("url") else ""
        lines.append(
            f"- **{finding['level']}** {finding['check']}"
            f"{location}: {finding['message']}"
        )
    lines.extend([
        "",
        "## Lifecycle",
        "",
        report.get("lifecycle", {}).get("policy", "Not documented."),
        "",
        "This report contains no cookies, authorization data or environment values.",
        "",
    ])
    return "\n".join(lines)


def write_seo_reports(
    report: dict[str, Any],
    *,
    json_path: str | Path | None,
    markdown_path: str | Path | None,
) -> None:
    if json_path:
        destination = Path(json_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    if markdown_path:
        destination = Path(markdown_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(render_markdown_report(report), encoding="utf-8")

def _domain_matrix(
    *,
    fetcher: ProductionFetcher,
    base_url: str,
    railway_hostname: str | None,
    findings: list[AuditFinding],
) -> list[dict[str, Any]]:
    base_host = urlsplit(base_url).hostname or ""
    www_host = f"www.{base_host}" if not base_host.startswith("www.") else base_host[4:]
    fetcher.register_hostname(www_host)
    variants = [
        (f"https://{base_host}/", True, "canonical HTTPS"),
        (f"http://{base_host}/", True, "canonical HTTP"),
        (f"https://{www_host}/", False, "www HTTPS"),
        (f"http://{www_host}/", False, "www HTTP"),
    ]
    rows: list[dict[str, Any]] = []
    canonical_url = f"{base_url}/"
    for requested_url, required, label in variants:
        try:
            response = fetcher.fetch_url(
                requested_url,
                follow_redirects=True,
                user_agent=_NORMAL_USER_AGENT,
            )
        except (VerificationError, URLError, socket.timeout) as exc:
            if required:
                level = "FAIL"
                result = "FAIL"
                message = f"{label} request failed: {_exception_message(exc)}"
            else:
                level = "WARNING"
                result = "NOT CHECKED"
                message = (
                    f"{label} is not reachable. This is acceptable only for "
                    f"an intentional apex-only DNS policy: {_exception_message(exc)}"
                )
            _add_finding(findings, level, "domain-matrix", message, requested_url)
            rows.append({
                "requested_url": requested_url,
                "status": None,
                "final_url": None,
                "redirect_chain": [],
                "result": result,
            })
            continue

        row = _response_record(response)
        errors: list[str] = []
        if response.status != 200:
            errors.append(f"final response is HTTP {response.status}")
        if response.final_url != canonical_url:
            errors.append(
                f"final URL is {response.final_url!r}, expected {canonical_url!r}"
            )
        if requested_url == canonical_url and response.redirect_chain:
            errors.append("canonical HTTPS origin redirects")
        if requested_url != canonical_url and len(response.redirect_chain) != 1:
            errors.append("non-canonical origin must use exactly one redirect")
        row["result"] = "FAIL" if errors else "PASS"
        rows.append(row)
        for error in errors:
            _add_finding(findings, "FAIL", "domain-matrix", error, requested_url)
        if not errors:
            _add_finding(
                findings,
                "PASS",
                "domain-matrix",
                f"{label} resolves to the canonical origin",
                requested_url,
            )

    if not railway_hostname:
        _add_finding(
            findings,
            "NOT CHECKED",
            "railway-hostname",
            (
                "Railway public hostname was not supplied. Pass "
                "--railway-hostname to verify redirect or inaccessibility."
            ),
        )
        return rows

    fetcher.register_hostname(railway_hostname)
    railway_url = f"https://{railway_hostname.strip().rstrip('/')}/"
    try:
        response = fetcher.fetch_url(
            railway_url,
            follow_redirects=True,
            user_agent=_NORMAL_USER_AGENT,
        )
    except (VerificationError, URLError, socket.timeout) as exc:
        _add_finding(
            findings,
            "FAIL",
            "railway-hostname",
            f"Explicit Railway hostname could not be checked: {_exception_message(exc)}",
            railway_url,
        )
        rows.append({
            "requested_url": railway_url,
            "status": None,
            "final_url": None,
            "redirect_chain": [],
            "result": "FAIL",
        })
        return rows

    row = _response_record(response)
    inaccessible = response.status in {400, 403, 404, 421}
    redirected = (
        response.status == 200
        and response.final_url == canonical_url
        and len(response.redirect_chain) == 1
    )
    row["result"] = "PASS" if inaccessible or redirected else "FAIL"
    rows.append(row)
    if row["result"] == "PASS":
        _add_finding(
            findings,
            "PASS",
            "railway-hostname",
            "Railway hostname is inaccessible or redirects once to canonical",
            railway_url,
        )
    else:
        _add_finding(
            findings,
            "FAIL",
            "railway-hostname",
            "Railway hostname exposes duplicate content or an unsafe redirect chain",
            railway_url,
        )
    return rows


def _audit_favicon(
    *,
    fetcher: ProductionFetcher,
    base_url: str,
    home_document: HtmlDocument | None,
    findings: list[AuditFinding],
) -> dict[str, Any]:
    if home_document is None or not home_document.icon_urls:
        _add_finding(
            findings,
            "FAIL",
            "favicon",
            "Home page has no rel=icon",
            f"{base_url}/",
        )
        return {}
    if len(home_document.icon_urls) > 1:
        _add_finding(
            findings,
            "WARNING",
            "favicon",
            "Multiple favicon declarations found; verify browser precedence",
            f"{base_url}/",
        )
    icon_url = urljoin(f"{base_url}/", home_document.icon_urls[0])
    response = _fetch_for_audit(
        fetcher,
        findings,
        icon_url,
        check="favicon",
    )
    if response is None:
        return {"url": icon_url}
    errors: list[str] = []
    content_type = response.headers.get("content-type", "").casefold()
    if response.status != 200:
        errors.append(f"favicon returned HTTP {response.status}")
    if not content_type.startswith("image/"):
        errors.append(f"favicon Content-Type is {content_type!r}")
    if response.text.lstrip().casefold().startswith(("<!doctype", "<html")):
        errors.append("favicon URL returns HTML")
    if response.headers.get("x-content-type-options", "").casefold() != "nosniff":
        errors.append("favicon lacks nosniff")
    for error in errors:
        _add_finding(findings, "FAIL", "favicon", error, icon_url)
    if not errors:
        _add_finding(
            findings,
            "PASS",
            "favicon",
            "Favicon is a real image response",
            icon_url,
        )
    result = _response_record(response)
    result["url"] = icon_url
    return result


def _audit_bot_parity(
    *,
    fetcher: ProductionFetcher,
    representative_urls: list[str],
    findings: list[AuditFinding],
) -> dict[str, Any]:
    user_agents = {
        "normal": _NORMAL_USER_AGENT,
        "googlebot": _GOOGLEBOT_USER_AGENT,
        "yandexbot": _YANDEXBOT_USER_AGENT,
    }
    result: dict[str, Any] = {"pages": {}, "robots": {}}
    for url in representative_urls:
        signatures: dict[str, Any] = {}
        for label, user_agent in user_agents.items():
            response = _fetch_for_audit(
                fetcher,
                findings,
                url,
                check="bot-parity",
                user_agent=user_agent,
            )
            if response is not None:
                signatures[label] = _bot_signature(response)
        result["pages"][url] = signatures
        if len(signatures) == len(user_agents):
            baseline = signatures["normal"]
            mismatches = [
                label
                for label in ("googlebot", "yandexbot")
                if signatures[label] != baseline
            ]
            if mismatches:
                _add_finding(
                    findings,
                    "FAIL",
                    "bot-parity",
                    "HTML differs for: " + ", ".join(mismatches),
                    url,
                )
            else:
                _add_finding(
                    findings,
                    "PASS",
                    "bot-parity",
                    "Normal browser, Googlebot and YandexBot receive equivalent HTML",
                    url,
                )

    robots_url = f"{fetcher.base_url}/robots.txt"
    robot_bodies: dict[str, dict[str, Any]] = {}
    for label, user_agent in user_agents.items():
        response = _fetch_for_audit(
            fetcher,
            findings,
            robots_url,
            check="robots-bot-parity",
            user_agent=user_agent,
        )
        if response is not None:
            robot_bodies[label] = {
                "status": response.status,
                "sha256": hashlib.sha256(response.body).hexdigest(),
            }
    result["robots"] = robot_bodies
    if len(robot_bodies) == len(user_agents):
        if len({
            (item["status"], item["sha256"])
            for item in robot_bodies.values()
        }) == 1:
            _add_finding(
                findings,
                "PASS",
                "robots-bot-parity",
                "robots.txt is identical for all audited user agents",
                robots_url,
            )
        else:
            _add_finding(
                findings,
                "FAIL",
                "robots-bot-parity",
                "robots.txt differs by user agent",
                robots_url,
            )
    return result


def _lifecycle_observations(
    documents: dict[str, HtmlDocument],
) -> dict[str, Any]:
    today = datetime.now(timezone.utc).date()
    observed: list[dict[str, Any]] = []
    for url, document in documents.items():
        if not _COMPETITION_PATH.fullmatch(urlsplit(url).path):
            continue
        values, _ = parse_json_ld(document)
        events = [
            node
            for value in values
            for node in _schema_nodes(value)
            if node.get("@type") == "Event"
        ]
        start_date = events[0].get("startDate") if events else None
        timing = "unknown"
        if isinstance(start_date, str):
            try:
                event_date = datetime.fromisoformat(
                    start_date.replace("Z", "+00:00")
                ).date()
                timing = "past" if event_date < today else "current-or-future"
            except ValueError:
                timing = "malformed"
        text = document.main_text.casefold()
        registration = (
            "open" if "\u043f\u0440\u0438\u0451\u043c \u0437\u0430\u044f\u0432\u043e\u043a \u043e\u0442\u043a\u0440\u044b\u0442" in text
            else "closed" if "\u0440\u0435\u0433\u0438\u0441\u0442\u0440\u0430\u0446\u0438\u044f \u0437\u0430\u0432\u0435\u0440\u0448\u0435\u043d\u0430" in text
            else "unknown"
        )
        observed.append({
            "url": url,
            "event_start_date": start_date,
            "event_timing_utc": timing,
            "registration_state_from_html": registration,
            "event_schema_present": bool(events),
        })
    return {
        "policy": (
            "Publication is controlled only by is_published. Registration closes "
            "after application_deadline in APP_TIMEZONE; an elapsed event_date "
            "does not automatically unpublish or redirect a competition page. "
            "Owners must unpublish or deliberately retain/archive past events."
        ),
        "observed": observed,
        "limitations": [
            "The read-only HTTP audit cannot distinguish unpublished from deleted IDs without a supplied known unpublished ID.",
            "Missing/minimal database fields are inferred only from rendered HTML and honest JSON-LD omission.",
            "500/503 HTML is not triggered deliberately in production.",
        ],
    }

def run_seo_audit(
    base_url: str,
    *,
    timeout: float = 10.0,
    competition_id: int | None = None,
    unpublished_competition_id: int | None = None,
    railway_hostname: str | None = None,
    max_requests: int = _DEFAULT_MAX_REQUESTS,
    _fetcher: ProductionFetcher | None = None,
) -> dict[str, Any]:
    canonical_base = validate_public_base_url(base_url)
    base_hostname = urlsplit(canonical_base).hostname or ""
    if competition_id is not None and competition_id < 1:
        raise VerificationError("--competition-id must be positive")
    if unpublished_competition_id is not None and unpublished_competition_id < 1:
        raise VerificationError("--unpublished-competition-id must be positive")

    fetcher = _fetcher or ProductionFetcher(
        canonical_base,
        timeout=timeout,
        max_requests=max_requests,
    )
    findings: list[AuditFinding] = []
    domain_matrix = _domain_matrix(
        fetcher=fetcher,
        base_url=canonical_base,
        railway_hostname=railway_hostname,
        findings=findings,
    )

    robots_url = f"{canonical_base}/robots.txt"
    sitemap_url = f"{canonical_base}/sitemap.xml"
    robots_response = _fetch_for_audit(
        fetcher, findings, robots_url, check="robots"
    )
    sitemap_response = _fetch_for_audit(
        fetcher, findings, sitemap_url, check="sitemap"
    )
    sitemap_urls: list[str] = []
    robots_record: dict[str, Any] = {}
    sitemap_record: dict[str, Any] = {}

    if robots_response is not None:
        robots_record = _response_record(robots_response)
        robots_errors: list[str] = []
        robots_text = robots_response.text
        if robots_response.status != 200:
            robots_errors.append(f"robots.txt returned {robots_response.status}")
        if "user-agent: *" not in robots_text.casefold():
            robots_errors.append("robots.txt lacks User-agent: *")
        if "allow: /" not in robots_text.casefold():
            robots_errors.append("robots.txt lacks Allow: /")
        for path in ("/docs", "/redoc", "/openapi.json"):
            if f"disallow: {path}" not in robots_text.casefold():
                robots_errors.append(f"robots.txt does not disallow {path}")
        if f"sitemap: {sitemap_url}".casefold() not in robots_text.casefold():
            robots_errors.append("robots.txt references the wrong sitemap")
        if robots_response.headers.get(
            "x-content-type-options", ""
        ).casefold() != "nosniff":
            robots_errors.append("robots.txt lacks nosniff")
        for error in robots_errors:
            _add_finding(findings, "FAIL", "robots", error, robots_url)
        if not robots_errors:
            _add_finding(
                findings,
                "PASS",
                "robots",
                "robots.txt exposes the canonical sitemap and expected rules",
                robots_url,
            )

    if sitemap_response is not None:
        sitemap_record = _response_record(sitemap_response)
        sitemap_errors: list[str] = []
        if sitemap_response.status != 200:
            sitemap_errors.append(
                f"sitemap.xml returned {sitemap_response.status}"
            )
        content_type = sitemap_response.headers.get("content-type", "").casefold()
        if "xml" not in content_type:
            sitemap_errors.append(
                f"sitemap.xml Content-Type is {content_type!r}"
            )
        if sitemap_response.headers.get(
            "x-content-type-options", ""
        ).casefold() != "nosniff":
            sitemap_errors.append("sitemap.xml lacks nosniff")
        try:
            sitemap_urls = parse_sitemap(
                sitemap_response.body,
                expected_origin=canonical_base,
            )
        except VerificationError as exc:
            sitemap_errors.append(str(exc))
        if len(sitemap_urls) != len(set(sitemap_urls)):
            sitemap_errors.append("sitemap.xml contains duplicate URLs")
        missing_static = [
            f"{canonical_base}{path}" if path != "/" else f"{canonical_base}/"
            for path in _INDEXABLE_STATIC_PATHS
            if (
                f"{canonical_base}{path}" if path != "/"
                else f"{canonical_base}/"
            ) not in sitemap_urls
        ]
        if missing_static:
            sitemap_errors.append(
                "sitemap.xml lacks static URLs: " + ", ".join(missing_static)
            )
        try:
            root = _safe_xml_root(sitemap_response.body)
        except (ET.ParseError, VerificationError):
            root = None
        if root is not None:
            today = datetime.now(timezone.utc).date()
            for element in root.iter():
                if element.tag.rsplit("}", 1)[-1] != "lastmod" or not element.text:
                    continue
                raw_lastmod = element.text.strip()
                try:
                    lastmod = datetime.fromisoformat(
                        raw_lastmod.replace("Z", "+00:00")
                    ).date()
                except ValueError:
                    sitemap_errors.append(
                        f"sitemap.xml has malformed lastmod {raw_lastmod!r}"
                    )
                else:
                    if lastmod > today:
                        sitemap_errors.append(
                            f"sitemap.xml has future lastmod {raw_lastmod!r}"
                        )
        for error in sitemap_errors:
            _add_finding(findings, "FAIL", "sitemap", error, sitemap_url)
        if not sitemap_errors:
            _add_finding(
                findings,
                "PASS",
                "sitemap",
                f"Valid canonical sitemap with {len(sitemap_urls)} unique URLs",
                sitemap_url,
            )

    audited_sitemap_urls = sitemap_urls[:40]
    if len(sitemap_urls) > len(audited_sitemap_urls):
        _add_finding(
            findings,
            "NOT CHECKED",
            "sitemap-pages",
            (
                f"{len(sitemap_urls) - len(audited_sitemap_urls)} sitemap URLs "
                "were skipped by the 40-page safety cap"
            ),
            sitemap_url,
        )

    responses: dict[str, HttpResponse] = {}
    documents: dict[str, HtmlDocument] = {}
    pages: list[dict[str, Any]] = []
    for url in audited_sitemap_urls:
        response = _fetch_for_audit(
            fetcher, findings, url, check="sitemap-page"
        )
        if response is None:
            continue
        responses[url] = response
        document, summary = _html_snapshot(
            response,
            expected_url=url,
            base_hostname=base_hostname,
            findings=findings,
        )
        documents[url] = document
        pages.append(summary)

    home_url = f"{canonical_base}/"
    catalog_url = f"{canonical_base}/competitions"
    home_document = documents.get(home_url)
    if home_document is not None:
        values, _ = parse_json_ld(home_document)
        brand_nodes = [
            node
            for value in values
            for node in _schema_nodes(value)
            if node.get("@type") in {"WebSite", "Organization"}
        ]
        for node in brand_nodes:
            if node.get("name") != "ArtFlow":
                _add_finding(
                    findings,
                    "FAIL",
                    "site-name",
                    f"{node.get('@type')} name is not ArtFlow",
                    home_url,
                )
            if node.get("url") not in {canonical_base, home_url}:
                _add_finding(
                    findings,
                    "FAIL",
                    "site-name",
                    f"{node.get('@type')} URL is not canonical",
                    home_url,
                )
        if brand_nodes and not any(
            item.level == "FAIL" and item.check == "site-name"
            for item in findings
        ):
            _add_finding(
                findings,
                "PASS",
                "site-name",
                "ArtFlow brand and canonical URL are consistent",
                home_url,
            )

    title_urls: dict[str, list[str]] = {}
    description_urls: dict[str, list[str]] = {}
    for page in pages:
        title_urls.setdefault(page["title"], []).append(page["url"])
        description_urls.setdefault(page["description"], []).append(page["url"])
    for title, urls in title_urls.items():
        if title and len(urls) > 1:
            _add_finding(
                findings,
                "FAIL",
                "duplicate-title",
                "Duplicate title across: " + ", ".join(urls),
            )
    for description, urls in description_urls.items():
        if description and len(urls) > 1:
            _add_finding(
                findings,
                "WARNING",
                "duplicate-description",
                "Duplicate meta description across: " + ", ".join(urls),
            )

    catalog_document = documents.get(catalog_url)
    sitemap_competitions = {
        url for url in sitemap_urls
        if _COMPETITION_PATH.fullmatch(urlsplit(url).path)
    }
    catalog_competitions: set[str] = set()
    if catalog_document is not None:
        for anchor in catalog_document.anchors:
            target = _canonical_link_target(
                canonical_base, str(anchor.get("href", ""))
            )
            if target and _COMPETITION_PATH.fullmatch(urlsplit(target[0]).path):
                catalog_competitions.add(target[0])
    if catalog_competitions != sitemap_competitions:
        _add_finding(
            findings,
            "FAIL",
            "competition-discovery",
            (
                "Catalog and sitemap competition URLs differ: catalog-only="
                f"{sorted(catalog_competitions - sitemap_competitions)}, "
                f"sitemap-only={sorted(sitemap_competitions - catalog_competitions)}"
            ),
            catalog_url,
        )
    elif sitemap_competitions:
        _add_finding(
            findings,
            "PASS",
            "competition-discovery",
            "Published competition URLs match between catalog and sitemap",
            catalog_url,
        )

    for source_url, document in list(documents.items()):
        for anchor in document.anchors:
            target = _canonical_link_target(
                canonical_base, str(anchor.get("href", ""))
            )
            if target is None:
                continue
            target_url = target[0]
            if (
                target_url in responses
                or target_url.startswith(f"{canonical_base}/static/")
            ):
                continue
            response = _fetch_for_audit(
                fetcher,
                findings,
                target_url,
                check="internal-link-target",
            )
            if response is not None:
                responses[target_url] = response
                if response.status == 200 and "text/html" in response.headers.get(
                    "content-type", ""
                ).casefold():
                    documents[target_url] = parse_html_document(response.text)
                    _add_finding(
                        findings,
                        "WARNING",
                        "sitemap-coverage",
                        "Indexable internal page is linked but absent from sitemap",
                        target_url,
                    )

    internal_graph = _audit_internal_graph(
        base_url=canonical_base,
        documents=documents,
        responses=responses,
        sitemap_urls=sitemap_urls,
        findings=findings,
    )

    endpoint_results: dict[str, Any] = {}
    for path in ("/health", "/health/db"):
        url = f"{canonical_base}{path}"
        response = _fetch_for_audit(
            fetcher, findings, url, check="health-indexing"
        )
        if response is None:
            continue
        endpoint_results[path] = _response_record(response)
        errors: list[str] = []
        expected_statuses = {200} if path == "/health" else {200, 503}
        if response.status not in expected_statuses:
            errors.append(f"{path} returned {response.status}")
        if "noindex" not in response.headers.get("x-robots-tag", "").casefold():
            errors.append(f"{path} lacks X-Robots-Tag noindex")
        if response.headers.get(
            "x-content-type-options", ""
        ).casefold() != "nosniff":
            errors.append(f"{path} lacks nosniff")
        secret_markers = (
            "database_url", "postgresql://", "password=", "traceback (",
        )
        if any(marker in response.text.casefold() for marker in secret_markers):
            errors.append(f"{path} exposes a secret or traceback marker")
        for error in errors:
            _add_finding(findings, "FAIL", "health-indexing", error, url)
        if not errors:
            _add_finding(
                findings,
                "PASS",
                "health-indexing",
                f"{path} is safe and non-indexable",
                url,
            )

    missing_cases = [
        ("/docs", True),
        ("/redoc", True),
        ("/openapi.json", True),
        ("/__artflow_seo_missing__", True),
        ("/competitions/999999999999", True),
        ("/competitions/not-an-id", True),
        ("/static/__artflow_missing__.css", False),
    ]
    if unpublished_competition_id is not None:
        missing_cases.append((
            f"/competitions/{unpublished_competition_id}",
            True,
        ))
    else:
        _add_finding(
            findings,
            "NOT CHECKED",
            "unpublished-competition",
            (
                "No known unpublished competition ID was supplied; deleted and "
                "unpublished states cannot be distinguished over public HTTP."
            ),
        )
    for path, html_expected in missing_cases:
        url = f"{canonical_base}{path}"
        response = _fetch_for_audit(
            fetcher, findings, url, check="real-404"
        )
        if response is not None:
            endpoint_results[path] = _response_record(response)
            _audit_missing_response(
                response,
                expected_url=url,
                findings=findings,
                html_expected=html_expected,
            )

    query_variants: list[dict[str, Any]] = []
    for query in (
        "?utm_source=seo-audit",
        "?utm_medium=verification",
        "?unexpected_parameter=1",
    ):
        url = f"{catalog_url}{query}"
        response = _fetch_for_audit(
            fetcher, findings, url, check="query-canonical"
        )
        if response is None:
            continue
        row = _response_record(response)
        query_variants.append(row)
        document = parse_html_document(response.text)
        errors = canonical_errors(
            document,
            expected_url=catalog_url,
            indexable=True,
        )
        if response.status != 200:
            errors.append(f"query variant returned {response.status}")
        for error in errors:
            _add_finding(findings, "FAIL", "query-canonical", error, url)
        if not errors:
            _add_finding(
                findings,
                "PASS",
                "query-canonical",
                "Query variant points to clean canonical",
                url,
            )

    trailing_variants: list[dict[str, Any]] = []
    for path in ("/competitions/", "/faq/", "/about/"):
        url = f"{canonical_base}{path}"
        response = _fetch_for_audit(
            fetcher,
            findings,
            url,
            check="trailing-slash",
            follow_redirects=True,
        )
        if response is None:
            continue
        row = _response_record(response)
        trailing_variants.append(row)
        expected = f"{canonical_base}{path.rstrip('/')}"
        errors: list[str] = []
        if response.status != 200:
            errors.append(f"trailing-slash variant ended with {response.status}")
        if response.final_url != expected:
            errors.append(
                f"trailing-slash final URL is {response.final_url!r}"
            )
        if len(response.redirect_chain) != 1:
            errors.append("trailing-slash variant must redirect exactly once")
        for error in errors:
            _add_finding(findings, "FAIL", "trailing-slash", error, url)
        if not errors:
            _add_finding(
                findings,
                "PASS",
                "trailing-slash",
                "Variant redirects once to canonical URL",
                url,
            )

    favicon = _audit_favicon(
        fetcher=fetcher,
        base_url=canonical_base,
        home_document=home_document,
        findings=findings,
    )

    deep_links: list[dict[str, Any]] = []
    for url in sorted(sitemap_competitions):
        document = documents.get(url)
        if document is None:
            continue
        competition_path_match = _COMPETITION_PATH.fullmatch(urlsplit(url).path)
        expected_id = int(competition_path_match.group(1)) if competition_path_match else 0
        ids = _deep_link_ids(responses[url].text)
        telegram_start_links = [
            str(anchor.get("href", ""))
            for anchor in document.anchors
            if "t.me/" in str(anchor.get("href", ""))
            and "start=" in str(anchor.get("href", ""))
        ]
        valid = all(
            _TELEGRAM_DEEP_LINK.fullmatch(link)
            and expected_id in _deep_link_ids(f'<a href="{link}"></a>')
            for link in telegram_start_links
        )
        registration_open = "\u043f\u0440\u0438\u0451\u043c \u0437\u0430\u044f\u0432\u043e\u043a \u043e\u0442\u043a\u0440\u044b\u0442" in document.main_text.casefold()
        if registration_open and expected_id not in ids:
            valid = False
        deep_links.append({
            "url": url,
            "competition_id": expected_id,
            "registration_open": registration_open,
            "deep_link_ids": sorted(ids),
            "valid": valid,
        })
        if valid:
            _add_finding(
                findings,
                "PASS",
                "telegram-deep-link",
                "Telegram deep link preserves competition_{id}",
                url,
            )
        else:
            _add_finding(
                findings,
                "FAIL",
                "telegram-deep-link",
                "Telegram deep link is malformed or does not match the page ID",
                url,
            )

    selected_detail_url: str | None = None
    if competition_id is not None:
        selected_detail_url = f"{canonical_base}/competitions/{competition_id}"
    elif sitemap_competitions:
        selected_detail_url = sorted(sitemap_competitions)[0]
    representative_urls = [home_url, catalog_url]
    if selected_detail_url in documents:
        representative_urls.append(selected_detail_url)
    bot_parity = _audit_bot_parity(
        fetcher=fetcher,
        representative_urls=representative_urls,
        findings=findings,
    )

    lifecycle = _lifecycle_observations(documents)
    _add_finding(
        findings,
        "NOT CHECKED",
        "error-page-production",
        (
            "500 and 503 HTML pages are covered by local tests but are not "
            "deliberately triggered against production."
        ),
    )
    _add_finding(
        findings,
        "NOT CHECKED",
        "search-engine-panels",
        (
            "Google Search Console URL Inspection and Yandex Webmaster status "
            "require owner access and are recorded in the runbook."
        ),
    )

    summary = {
        level: sum(item.level == level for item in findings)
        for level in _REPORT_LEVELS
    }
    report = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "base_url": canonical_base,
        "mode": "production-seo-audit",
        "overall": "FAIL" if summary["FAIL"] else "PASS",
        "request_count": fetcher.request_count,
        "max_requests": fetcher.max_requests,
        "summary": summary,
        "findings": [item.as_dict() for item in findings],
        "domain_matrix": domain_matrix,
        "robots": robots_record,
        "sitemap": {
            **sitemap_record,
            "urls": sitemap_urls,
            "audited_url_count": len(audited_sitemap_urls),
        },
        "pages": pages,
        "internal_links": internal_graph,
        "query_variants": query_variants,
        "trailing_slash_variants": trailing_variants,
        "endpoints": endpoint_results,
        "favicon": favicon,
        "telegram_deep_links": deep_links,
        "bot_parity": bot_parity,
        "lifecycle": lifecycle,
        "safety": {
            "methods": ["GET", "HEAD"],
            "external_html_links_fetched": False,
            "cookies_sent": False,
            "authorization_sent": False,
            "database_writes": False,
            "telegram_requests_sent": False,
        },
    }
    return report
def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Perform non-destructive checks against deployed ArtFlowWeb.",
    )
    parser.add_argument("base_url", help="Public HTTPS origin, without a path")
    parser.add_argument(
        "--competition-id",
        type=int,
        help="Known published competition to inspect first",
    )
    parser.add_argument(
        "--seo-audit",
        action="store_true",
        help="Run the bounded production SEO audit and collect all findings",
    )
    parser.add_argument(
        "--report",
        help="Write a JSON SEO report to this local path",
    )
    parser.add_argument(
        "--markdown-report",
        help="Write a Markdown SEO report to this local path",
    )
    parser.add_argument(
        "--unpublished-competition-id",
        type=int,
        help="Known unpublished competition ID expected to return 404",
    )
    parser.add_argument(
        "--railway-hostname",
        help="Confirmed Railway public hostname, without scheme or path",
    )
    parser.add_argument(
        "--max-requests",
        type=int,
        default=_DEFAULT_MAX_REQUESTS,
        help=(
            "Hard request cap for --seo-audit "
            f"(default {_DEFAULT_MAX_REQUESTS}, maximum 200)"
        ),
    )
    parser.add_argument("--timeout", type=float, default=10.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        if arguments.seo_audit:
            report = run_seo_audit(
                arguments.base_url,
                timeout=arguments.timeout,
                competition_id=arguments.competition_id,
                unpublished_competition_id=(
                    arguments.unpublished_competition_id
                ),
                railway_hostname=arguments.railway_hostname,
                max_requests=arguments.max_requests,
            )
            write_seo_reports(
                report,
                json_path=arguments.report,
                markdown_path=arguments.markdown_report,
            )
            summary = report["summary"]
            print(
                "Production SEO audit: "
                + ", ".join(
                    f"{level}={summary[level]}" for level in _REPORT_LEVELS
                )
            )
            print(
                f"Requests: {report['request_count']} / "
                f"{report['max_requests']}"
            )
            if arguments.report:
                print(f"JSON report: {arguments.report}")
            if arguments.markdown_report:
                print(f"Markdown report: {arguments.markdown_report}")
            if report["overall"] == "FAIL":
                print(
                    "Production SEO audit found FAIL findings",
                    file=sys.stderr,
                )
                return 1
            print("Production SEO audit passed")
            return 0

        if arguments.report or arguments.markdown_report:
            raise VerificationError(
                "--report and --markdown-report require --seo-audit"
            )
        checks = verify(
            arguments.base_url,
            timeout=max(1.0, min(arguments.timeout, 30.0)),
            competition_id=arguments.competition_id,
        )
    except (VerificationError, URLError, socket.timeout, OSError) as exc:
        print(f"Production verification failed: {exc}", file=sys.stderr)
        return 1

    for check in checks:
        print(f"[ok] {check}")
    print("Production verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
