from __future__ import annotations

import json
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlsplit

import pytest

from scripts.verify_production import (
    HttpResponse,
    VerificationError,
    _bot_signature,
    canonical_errors,
    json_ld_errors,
    parse_html_document,
    parse_json_ld,
    parse_sitemap,
    render_markdown_report,
    run_seo_audit,
    schema_type_names,
    soft_404_reasons,
    write_seo_reports,
)


BASE_URL = "https://artflow.example.test"
STATIC_PATHS = (
    "/",
    "/competitions",
    "/faq",
    "/about",
    "/how-to-participate",
)


def response_headers(
    content_type: str = "text/html; charset=utf-8",
    *,
    x_robots_tag: str | None = None,
) -> dict[str, str]:
    headers = {
        "content-type": content_type,
        "content-security-policy": (
            "default-src 'self'; script-src 'self'; style-src 'self'"
        ),
        "referrer-policy": "no-referrer",
        "x-frame-options": "DENY",
        "permissions-policy": "camera=()",
        "x-content-type-options": "nosniff",
        "strict-transport-security": "max-age=31536000",
    }
    if x_robots_tag:
        headers["x-robots-tag"] = x_robots_tag
    return headers


def breadcrumb_schema(name: str, path: str) -> dict:
    return {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {
                "@type": "ListItem",
                "position": 1,
                "name": "\u0413\u043b\u0430\u0432\u043d\u0430\u044f",
                "item": f"{BASE_URL}/",
            },
            {
                "@type": "ListItem",
                "position": 2,
                "name": name,
                "item": f"{BASE_URL}{path}",
            },
        ],
    }


def html_page(
    path: str,
    *,
    canonical_override: str | None = None,
    event: bool = True,
    organizer: bool = False,
    malformed_deep_link: bool = False,
    soft_404: bool = False,
) -> str:
    canonical = (
        canonical_override
        if canonical_override is not None
        else f"{BASE_URL}{path}" if path != "/" else f"{BASE_URL}/"
    )
    slug = path.strip("/").replace("/", "-") or "home"
    title = f"ArtFlow production page {slug} with verified search metadata"
    h1 = "404 page not found" if soft_404 else f"ArtFlow {slug}"
    description = (
        f"Verified description for the ArtFlow {slug} page with factual "
        "competition information, navigation and participation details."
    )
    schemas: list[dict] = []
    breadcrumbs = ""
    if path == "/":
        schemas.extend([
            {
                "@context": "https://schema.org",
                "@type": "WebSite",
                "name": "ArtFlow",
                "url": f"{BASE_URL}/",
            },
            {
                "@context": "https://schema.org",
                "@type": "Organization",
                "name": "ArtFlow",
                "url": f"{BASE_URL}/",
                "logo": f"{BASE_URL}/static/images/artflow-logo-512.png",
            },
        ])
    else:
        schemas.append(breadcrumb_schema(h1, path))
        breadcrumbs = (
            '<nav class="breadcrumbs" aria-label="breadcrumbs"><ol>'
            '<li><a href="/">\u0413\u043b\u0430\u0432\u043d\u0430\u044f</a></li>'
            f'<li><span aria-current="page">{h1}</span></li>'
            "</ol></nav>"
        )
    if path == "/competitions/4" and event:
        event_schema = {
            "@context": "https://schema.org",
            "@type": "Event",
            "name": h1,
            "description": description,
            "startDate": "2026-09-05",
            "location": {
                "@type": "Place",
                "name": "Verified venue",
                "address": {
                    "@type": "PostalAddress",
                    "addressLocality": "Almaty",
                },
            },
            "url": canonical,
            "image": f"{BASE_URL}/static/images/artflow-logo-512.png",
        }
        if organizer:
            event_schema["organizer"] = {
                "@type": "Organization",
                "name": "ArtFlow",
            }
        schemas.append(event_schema)

    nav_links = "".join(
        f'<a href="{item}">{item}</a>'
        for item in ("/", "/competitions", "/faq", "/about", "/how-to-participate")
    )
    competition_link = (
        '<a href="/competitions/4">Competition four</a>'
        if path == "/competitions"
        else ""
    )
    deep_link = ""
    if path == "/competitions/4":
        href = (
            "https://t.me/ArtFlowBot?start=wrong_4"
            if malformed_deep_link
            else "https://t.me/ArtFlowBot?start=competition_4"
        )
        deep_link = (
            f'<a href="{href}" target="_blank" '
            'rel="noopener noreferrer">Apply</a>'
            "<p>\u041f\u0440\u0438\u0451\u043c \u0437\u0430\u044f\u0432\u043e\u043a \u043e\u0442\u043a\u0440\u044b\u0442</p>"
        )
    json_ld = "".join(
        '<script type="application/ld+json">'
        + json.dumps(item, ensure_ascii=False)
        + "</script>"
        for item in schemas
    )
    return f"""<!doctype html>
<html lang="ru"><head>
<title>{title}</title>
<meta name="description" content="{description}">
<meta name="robots" content="index, follow">
<meta property="og:type" content="website">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{description}">
<meta property="og:site_name" content="ArtFlow">
<meta property="og:url" content="{canonical}">
<meta property="og:image" content="{BASE_URL}/static/images/artflow-logo-512.png">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{title}">
<meta name="twitter:description" content="{description}">
<meta name="twitter:image" content="{BASE_URL}/static/images/artflow-logo-512.png">
<link rel="canonical" href="{canonical}">
<link rel="icon" href="/static/images/artflow-logo-512.png" type="image/png">
{json_ld}
</head><body>
<header><nav>{nav_links}</nav></header>
<main>{breadcrumbs}<h1>{h1}</h1><p>{description}</p><p>05.09.2026 Verified venue Almaty</p>{competition_link}{deep_link}</main>
</body></html>"""


def missing_html() -> bytes:
    return (
        "<!doctype html><html><head>"
        '<meta name="robots" content="noindex, nofollow">'
        "</head><body><main><h1>Page not found</h1></main></body></html>"
    ).encode()


class FixtureFetcher:
    def __init__(self, **options) -> None:
        self.base_url = BASE_URL
        self.max_requests = 80
        self.request_count = 0
        self.allowed_hostnames = {"artflow.example.test"}
        self.options = options

    def register_hostname(self, hostname: str) -> None:
        self.allowed_hostnames.add(hostname.casefold())

    def fetch_url(
        self,
        url: str,
        *,
        host: str | None = None,
        user_agent: str = "",
        follow_redirects: bool = True,
        method: str = "GET",
        max_redirects: int = 2,
    ) -> HttpResponse:
        del host, max_redirects
        assert method in {"GET", "HEAD"}
        self.request_count += 1
        parsed = urlsplit(url)
        if parsed.hostname == "www.artflow.example.test":
            raise URLError("fixture www DNS intentionally absent")
        if parsed.scheme == "http":
            final = f"{BASE_URL}/"
            return self._response(
                url,
                200,
                html_page("/").encode(),
                final_url=final,
                redirect_chain=(final,),
            )

        if parsed.path in {"/competitions/", "/faq/", "/about/"}:
            final_path = parsed.path.rstrip("/")
            final = f"{BASE_URL}{final_path}"
            return self._response(
                url,
                200,
                html_page(final_path).encode(),
                final_url=final,
                redirect_chain=(final,),
            )
        if parsed.path == "/robots.txt":
            body = (
                "User-agent: *\nAllow: /\nDisallow: /docs\n"
                "Disallow: /redoc\nDisallow: /openapi.json\n"
                f"Sitemap: {BASE_URL}/sitemap.xml\n"
            ).encode()
            return self._response(
                url, 200, body, content_type="text/plain; charset=utf-8"
            )
        if parsed.path == "/sitemap.xml":
            if self.options.get("malformed_sitemap"):
                body = b"<urlset><url>"
            else:
                urls = [
                    f"{BASE_URL}{path}" if path != "/" else f"{BASE_URL}/"
                    for path in (*STATIC_PATHS, "/competitions/4")
                ]
                if self.options.get("duplicate_sitemap"):
                    urls.append(urls[-1])
                body = (
                    '<?xml version="1.0" encoding="utf-8"?>'
                    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                    + "".join(f"<url><loc>{item}</loc></url>" for item in urls)
                    + "</urlset>"
                ).encode()
            return self._response(
                url, 200, body, content_type="application/xml"
            )
        if parsed.path == "/health":
            return self._response(
                url,
                200,
                b'{"status":"ok"}',
                content_type="application/json",
                x_robots_tag="noindex, nofollow",
            )
        if parsed.path == "/health/db":
            return self._response(
                url,
                200,
                b'{"status":"ok"}',
                content_type="application/json",
                x_robots_tag="noindex, nofollow",
            )
        if parsed.path == "/static/images/artflow-logo-512.png":
            return self._response(
                url, 200, b"\x89PNG\r\n\x1a\nfixture", content_type="image/png"
            )

        missing_paths = {
            "/docs",
            "/redoc",
            "/openapi.json",
            "/__artflow_seo_missing__",
            "/competitions/999999999999",
            "/competitions/not-an-id",
            "/static/__artflow_missing__.css",
        }
        if parsed.path in missing_paths:
            if (
                self.options.get("soft_missing")
                and parsed.path == "/__artflow_seo_missing__"
            ):
                return self._response(
                    url, 200, html_page("/", soft_404=True).encode()
                )
            content_type = (
                "text/css"
                if parsed.path.startswith("/static/")
                else "text/html; charset=utf-8"
            )
            body = b"" if content_type == "text/css" else missing_html()
            return self._response(url, 404, body, content_type=content_type)

        if parsed.path in (*STATIC_PATHS, "/competitions/4"):
            canonical_override = None
            if (
                self.options.get("bad_canonical")
                and parsed.path == "/faq"
            ):
                canonical_override = "http://artflow.example.test/faq?bad=1"
            page = html_page(
                parsed.path,
                canonical_override=canonical_override,
                organizer=(
                    self.options.get("organizer")
                    and parsed.path == "/competitions/4"
                ),
                malformed_deep_link=(
                    self.options.get("bad_deep_link")
                    and parsed.path == "/competitions/4"
                ),
            )
            if (
                self.options.get("bot_mismatch")
                and "Googlebot" in user_agent
                and parsed.path == "/"
            ):
                page = page.replace(
                    "ArtFlow production page home",
                    "Different bot-only title",
                    1,
                )
            return self._response(url, 200, page.encode())
        return self._response(url, 404, missing_html())

    @staticmethod
    def _response(
        requested_url: str,
        status: int,
        body: bytes,
        *,
        content_type: str = "text/html; charset=utf-8",
        x_robots_tag: str | None = None,
        final_url: str | None = None,
        redirect_chain: tuple[str, ...] = (),
    ) -> HttpResponse:
        return HttpResponse(
            status=status,
            headers=response_headers(
                content_type,
                x_robots_tag=x_robots_tag,
            ),
            body=body,
            requested_url=requested_url,
            final_url=final_url or requested_url,
            redirect_chain=redirect_chain,
        )


def audit_with_fixture(**options) -> dict:
    fetcher = FixtureFetcher(**options)
    return run_seo_audit(BASE_URL, _fetcher=fetcher)


def test_html_parser_extracts_search_metadata_and_visible_breadcrumbs():
    document = parse_html_document(html_page("/competitions/4"))

    assert document.title.startswith("ArtFlow")
    assert document.canonical_urls == [f"{BASE_URL}/competitions/4"]
    assert document.h1 == ["ArtFlow competitions-4"]
    assert document.breadcrumbs == ["\u0413\u043b\u0430\u0432\u043d\u0430\u044f", "ArtFlow competitions-4"]
    assert document.icon_urls == ["/static/images/artflow-logo-512.png"]
    assert document.anchors


@pytest.mark.parametrize(
    ("canonical", "expected_fragment"),
    [
        (None, "exactly one canonical"),
        ("/faq", "expected"),
        ("http://artflow.example.test/faq", "expected"),
        ("https://artflow.example.test/faq?x=1", "expected"),
        ("https://other.example.test/faq", "expected"),
    ],
)
def test_canonical_validator_rejects_non_canonical_values(
    canonical,
    expected_fragment,
):
    link = "" if canonical is None else f'<link rel="canonical" href="{canonical}">'
    document = parse_html_document(
        f'<meta name="robots" content="index, follow">{link}'
    )
    errors = canonical_errors(
        document,
        expected_url=f"{BASE_URL}/faq",
        indexable=True,
    )
    assert expected_fragment in " ".join(errors)


def test_canonical_validator_rejects_duplicates():
    document = parse_html_document(
        '<meta name="robots" content="index, follow">'
        f'<link rel="canonical" href="{BASE_URL}/faq">'
        f'<link rel="canonical" href="{BASE_URL}/faq">'
    )
    assert "exactly one canonical" in " ".join(
        canonical_errors(
            document,
            expected_url=f"{BASE_URL}/faq",
            indexable=True,
        )
    )


def test_non_indexable_page_requires_noindex_and_no_canonical():
    document = parse_html_document(
        f'<link rel="canonical" href="{BASE_URL}/missing">'
    )
    errors = canonical_errors(
        document,
        expected_url=f"{BASE_URL}/missing",
        indexable=False,
    )
    assert "noindex" in " ".join(errors)
    assert "canonical" in " ".join(errors)


@pytest.mark.parametrize(
    "heading",
    ["404", "\u0421\u0442\u0440\u0430\u043d\u0438\u0446\u0430 \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d\u0430", "Page not found", "\u041e\u0431\u044a\u0435\u043a\u0442 \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d"],
)
def test_soft_404_detector_flags_missing_content_returned_as_200(heading):
    document = parse_html_document(f"<title>{heading}</title><h1>{heading}</h1>")
    assert soft_404_reasons(200, document)
    assert soft_404_reasons(404, document) == []


def test_valid_sitemap_parser_preserves_canonical_urls():
    body = (
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"<url><loc>{BASE_URL}/</loc></url>"
        f"<url><loc>{BASE_URL}/faq</loc></url>"
        "</urlset>"
    ).encode()
    assert parse_sitemap(body, expected_origin=BASE_URL) == [
        f"{BASE_URL}/",
        f"{BASE_URL}/faq",
    ]


@pytest.mark.parametrize(
    "body",
    [
        b"<urlset>",
        b"<sitemapindex></sitemapindex>",
        (
            '<urlset><url><loc>http://artflow.example.test/</loc></url>'
            "</urlset>"
        ).encode(),
        (
            '<urlset><url><loc>https://evil.example.test/</loc></url>'
            "</urlset>"
        ).encode(),
        (
            '<urlset><url><loc>https://artflow.example.test/?x=1</loc></url>'
            "</urlset>"
        ).encode(),
    ],
)
def test_sitemap_parser_rejects_malformed_or_noncanonical_documents(body):
    with pytest.raises(VerificationError):
        parse_sitemap(body, expected_origin=BASE_URL)


def test_json_ld_parser_and_schema_type_collection():
    document = parse_html_document(html_page("/"))
    values, errors = parse_json_ld(document)
    assert errors == []
    assert schema_type_names(values) == ["Organization", "WebSite"]


def test_invalid_json_ld_is_reported_without_execution():
    document = parse_html_document(
        '<script type="application/ld+json">{"bad":</script>'
    )
    values, errors = parse_json_ld(document)
    assert values == []
    assert "invalid" in errors[0]


@pytest.mark.parametrize(
    "field",
    [
        "organizer",
        "offers",
        "aggregateRating",
        "review",
        "performer",
        "endDate",
        "eventStatus",
        "eventAttendanceMode",
    ],
)
def test_event_json_ld_rejects_unverified_fields(field):
    document = parse_html_document(html_page("/competitions/4"))
    values, _ = parse_json_ld(document)
    event = next(
        node
        for value in values
        for node in ([value] if isinstance(value, dict) else value)
        if node.get("@type") == "Event"
    )
    event[field] = "unverified"
    document.json_ld_sources = [
        json.dumps(value, ensure_ascii=False) for value in values
    ]
    errors, _ = json_ld_errors(
        document,
        page_url=f"{BASE_URL}/competitions/4",
        page_kind="competition",
    )
    assert field in " ".join(errors)


def test_competition_without_required_facts_does_not_require_false_event():
    document = parse_html_document(html_page("/competitions/4", event=False))
    errors, types = json_ld_errors(
        document,
        page_url=f"{BASE_URL}/competitions/4",
        page_kind="competition",
    )
    assert "Event" not in types
    assert "lacks Event" not in " ".join(errors)


def test_breadcrumb_json_ld_must_match_visible_breadcrumbs():
    document = parse_html_document(
        html_page("/faq").replace(
            '"name": "ArtFlow faq"',
            '"name": "Different label"',
            1,
        )
    )
    errors, _ = json_ld_errors(
        document,
        page_url=f"{BASE_URL}/faq",
        page_kind="static",
    )
    assert "visible breadcrumbs" in " ".join(errors)


def test_bot_signature_covers_main_content_and_structured_data():
    response = FixtureFetcher().fetch_url(f"{BASE_URL}/")
    signature = _bot_signature(response)
    assert signature["status"] == 200
    assert signature["schema_types"] == ["Organization", "WebSite"]
    assert len(signature["main_text_sha256"]) == 64


def test_full_fixture_audit_passes_without_production_network():
    report = audit_with_fixture()
    assert report["overall"] == "PASS"
    assert report["summary"]["FAIL"] == 0
    assert report["request_count"] <= report["max_requests"]
    assert report["sitemap"]["urls"][-1] == f"{BASE_URL}/competitions/4"
    assert report["telegram_deep_links"][0]["valid"] is True
    assert report["safety"]["external_html_links_fetched"] is False
    assert report["safety"]["cookies_sent"] is False
    assert report["safety"]["authorization_sent"] is False


@pytest.mark.parametrize(
    ("option", "check"),
    [
        ("bad_canonical", "indexable-page"),
        ("organizer", "indexable-page"),
        ("bad_deep_link", "telegram-deep-link"),
        ("bot_mismatch", "bot-parity"),
        ("duplicate_sitemap", "sitemap"),
        ("malformed_sitemap", "sitemap"),
        ("soft_missing", "real-404"),
    ],
)
def test_full_fixture_audit_reports_regressions(option, check):
    report = audit_with_fixture(**{option: True})
    assert report["overall"] == "FAIL"
    assert any(
        item["level"] == "FAIL" and item["check"] == check
        for item in report["findings"]
    )


def test_report_explicitly_marks_manual_and_unknown_checks():
    report = audit_with_fixture()
    not_checked = {
        item["check"]
        for item in report["findings"]
        if item["level"] == "NOT CHECKED"
    }
    assert {
        "railway-hostname",
        "unpublished-competition",
        "error-page-production",
        "search-engine-panels",
    }.issubset(not_checked)


def test_query_and_trailing_slash_variants_are_recorded():
    report = audit_with_fixture()
    assert len(report["query_variants"]) == 3
    assert len(report["trailing_slash_variants"]) == 3
    assert all(
        len(item["redirect_chain"]) == 1
        for item in report["trailing_slash_variants"]
    )


def test_markdown_and_json_reports_are_safe_and_readable(tmp_path: Path):
    report = audit_with_fixture()
    json_path = tmp_path / "seo.json"
    markdown_path = tmp_path / "seo.md"

    write_seo_reports(
        report,
        json_path=json_path,
        markdown_path=markdown_path,
    )

    loaded = json.loads(json_path.read_text(encoding="utf-8"))
    markdown = markdown_path.read_text(encoding="utf-8")
    assert loaded["base_url"] == BASE_URL
    assert "# ArtFlow production SEO audit" in markdown
    rendered = render_markdown_report(report).casefold()
    for forbidden in ("authorization:", "cookie:", "database_url", "password="):
        assert forbidden not in rendered


def test_report_domain_matrix_records_apex_redirect_and_www_dns_policy():
    report = audit_with_fixture()
    apex_http = next(
        item
        for item in report["domain_matrix"]
        if item["requested_url"] == "http://artflow.example.test/"
    )
    www_https = next(
        item
        for item in report["domain_matrix"]
        if item["requested_url"] == "https://www.artflow.example.test/"
    )
    assert apex_http["result"] == "PASS"
    assert apex_http["final_url"] == f"{BASE_URL}/"
    assert www_https["result"] == "NOT CHECKED"


def test_lifecycle_report_documents_current_model_without_changing_pages():
    report = audit_with_fixture()
    lifecycle = report["lifecycle"]
    assert "is_published" in lifecycle["policy"]
    assert "does not automatically unpublish" in lifecycle["policy"]
    assert lifecycle["observed"][0]["url"] == f"{BASE_URL}/competitions/4"


def test_html_parser_accepts_meta_charset_without_name_or_property():
    document = parse_html_document(
        '<meta charset="utf-8"><title>ArtFlow</title>'
    )


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("description", "Invisible description", "description"),
        ("startDate", "2030-01-01", "startDate"),
        (
            "location",
            {"@type": "Place", "name": "Invisible venue"},
            "location",
        ),
    ],
)
def test_event_json_ld_must_match_visible_content(field, value, expected):
    document = parse_html_document(html_page("/competitions/4"))
    values, _ = parse_json_ld(document)
    event = next(
        node
        for value_item in values
        for node in ([value_item] if isinstance(value_item, dict) else value_item)
        if node.get("@type") == "Event"
    )
    event[field] = value
    document.json_ld_sources = [
        json.dumps(item, ensure_ascii=False) for item in values
    ]
    errors, _ = json_ld_errors(
        document,
        page_url=f"{BASE_URL}/competitions/4",
        page_kind="competition",
    )
    assert expected in " ".join(errors)
    assert "visible" in " ".join(errors)


def test_sitemap_rejects_dtd_and_entity_declarations():
    body = (
        b'<!DOCTYPE urlset [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>'
        b'<urlset><url><loc>&xxe;</loc></url></urlset>'
    )
    with pytest.raises(VerificationError, match="forbidden"):
        parse_sitemap(body, expected_origin=BASE_URL)
