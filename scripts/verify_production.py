from __future__ import annotations

import argparse
import ipaddress
import json
import re
import socket
import sys
import unicodedata
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
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
    def __init__(self, base_url: str, *, timeout: float) -> None:
        self.base_url = validate_public_base_url(base_url)
        self.timeout = timeout
        self.opener = build_opener(_NoRedirectHandler())

    def get(self, path: str, *, host: str | None = None) -> HttpResponse:
        if not path.startswith("/") or path.startswith("//"):
            raise VerificationError("Verifier only requests same-origin paths")
        request = Request(
            urljoin(f"{self.base_url}/", path.lstrip("/")),
            method="GET",
            headers={
                "Accept": "text/html,application/json,text/plain;q=0.9,*/*;q=0.8",
                "User-Agent": "ArtFlowWeb-production-verifier/1.0",
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
        return HttpResponse(response.status, headers, _safe_read(response))


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
    _require(unknown_host.status == 400, "Unknown Host was not rejected with 400")
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
    parser.add_argument("--timeout", type=float, default=10.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        checks = verify(
            arguments.base_url,
            timeout=max(1.0, min(arguments.timeout, 30.0)),
            competition_id=arguments.competition_id,
        )
    except (VerificationError, URLError, socket.timeout) as exc:
        print(f"Production verification failed: {exc}", file=sys.stderr)
        return 1

    for check in checks:
        print(f"[ok] {check}")
    print("Production verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
