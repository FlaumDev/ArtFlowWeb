from __future__ import annotations

import argparse
from collections import Counter
import json
import statistics
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROUTES = (
    "/",
    "/competitions",
    "/competitions/7",
    "/faq",
    "/about",
    "/how-to-participate",
)
NUMERIC_METRICS = (
    "ttfb_ms",
    "dom_content_loaded_ms",
    "load_ms",
    "lcp_ms",
    "cls",
    "document_bytes",
    "transferred_bytes",
    "css_bytes",
    "js_bytes",
    "image_bytes",
    "request_count",
    "dom_nodes",
    "interaction_latency_ms",
)
REGRESSION_LIMIT = 0.10
REGRESSION_METRICS = (
    "document_bytes",
    "transferred_bytes",
    "css_bytes",
    "js_bytes",
    "request_count",
    "dom_nodes",
)
BUDGETS = {
    "javascript_bytes": 25 * 1024,
    "css_bytes": 75 * 1024,
    "html_bytes": 100 * 1024,
    "javascript_files": 1,
    "css_files": 4,
    "requests": 30,
    "fallback_image_bytes": 75 * 1024,
    "dom_nodes": 1200,
}


class AuditError(RuntimeError):
    pass


def validate_base_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    try:
        parsed.port
    except ValueError as exc:
        raise AuditError("base URL has an invalid port") from exc
    if (
        parsed.scheme.casefold() not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise AuditError("base URL must be an HTTP(S) origin without credentials or a path")
    return value.strip().rstrip("/")


def validate_routes(routes: list[str] | tuple[str, ...]) -> list[str]:
    normalized: list[str] = []
    for route in routes:
        if not route.startswith("/") or route.startswith("//"):
            raise AuditError(f"route must be same-origin and start with '/': {route!r}")
        normalized.append(route)
    return list(dict.fromkeys(normalized))


def _median(values: list[float | int]) -> float:
    return round(float(statistics.median(values)), 3)


def _aggregate_runs(path: str, runs: list[dict[str, Any]]) -> dict[str, Any]:
    first = runs[0]
    result: dict[str, Any] = {
        "path": path,
        "status": first["status"],
        "runs": len(runs),
    }
    for metric in NUMERIC_METRICS:
        values = [run[metric] for run in runs if run.get(metric) is not None]
        result[metric] = _median(values) if values else None
    candidates = Counter(
        (run.get("lcp_element"), run.get("lcp_resource"))
        for run in runs
        if run.get("lcp_element")
    )
    if candidates:
        (result["lcp_element"], result["lcp_resource"]), _ = candidates.most_common(1)[0]
    else:
        result["lcp_element"] = None
        result["lcp_resource"] = None
    result["lcp_candidates"] = [
        {"element": element, "resource": resource, "runs": count}
        for (element, resource), count in candidates.most_common()
    ]
    for name in (
        "largest_resource",
        "render_blocking_resources",
        "css_requests",
        "js_requests",
        "missing_image_dimensions",
        "eager_below_fold_images",
        "lazy_above_fold_images",
        "synchronous_scripts",
        "horizontal_overflow",
        "console_errors",
        "resource_errors",
        "blocked_third_party_requests",
        "interactions",
    ):
        result[name] = first[name]
    return result


_OBSERVER_SCRIPT = r"""
(() => {
    const state = {
        cls: 0,
        lcp: null,
        eventDurations: [],
    };
    window.__artflowPerformance = state;

    const describe = (element) => {
        if (!element) return null;
        const id = element.id ? `#${element.id}` : "";
        const classes = Array.from(element.classList || []).slice(0, 3);
        const className = classes.length ? `.${classes.join(".")}` : "";
        return `${element.tagName.toLowerCase()}${id}${className}`;
    };
    const safeUrl = (value) => {
        if (!value) return null;
        try {
            const parsed = new URL(value, location.href);
            return parsed.origin === location.origin
                ? parsed.pathname
                : `${parsed.origin}${parsed.pathname}`;
        } catch (_) {
            return null;
        }
    };

    try {
        new PerformanceObserver((list) => {
            const entries = list.getEntries();
            const entry = entries[entries.length - 1];
            if (entry) {
                state.lcp = {
                    time: entry.startTime,
                    size: entry.size,
                    element: describe(entry.element),
                    url: safeUrl(entry.url),
                };
            }
        }).observe({ type: "largest-contentful-paint", buffered: true });
    } catch (_) {}

    try {
        new PerformanceObserver((list) => {
            list.getEntries().forEach((entry) => {
                if (!entry.hadRecentInput) state.cls += entry.value;
            });
        }).observe({ type: "layout-shift", buffered: true });
    } catch (_) {}

    try {
        new PerformanceObserver((list) => {
            list.getEntries().forEach((entry) => {
                if (entry.interactionId) state.eventDurations.push(entry.duration);
            });
        }).observe({ type: "event", buffered: true, durationThreshold: 16 });
    } catch (_) {}
})();
"""


_COLLECT_SCRIPT = r"""
() => {
    const state = window.__artflowPerformance || {};
    const navigation = performance.getEntriesByType("navigation")[0];
    const resources = performance.getEntriesByType("resource");
    const safeUrl = (value) => {
        try {
            const parsed = new URL(value, location.href);
            return parsed.origin === location.origin
                ? parsed.pathname
                : `${parsed.origin}${parsed.pathname}`;
        } catch (_) {
            return "unknown";
        }
    };
    const transferred = (entry) => Number(entry.transferSize || entry.encodedBodySize || 0);
    const cssResources = resources.filter((entry) =>
        entry.initiatorType === "link" && /\.css(?:$|\?)/i.test(entry.name)
    );
    const jsResources = resources.filter((entry) =>
        entry.initiatorType === "script" || /\.js(?:$|\?)/i.test(entry.name)
    );
    const imageResources = resources.filter((entry) => entry.initiatorType === "img");
    const largest = resources.reduce(
        (current, entry) => transferred(entry) > transferred(current) ? entry : current,
        { name: "", transferSize: 0, encodedBodySize: 0 }
    );
    const images = Array.from(document.images).map((image) => {
        const rect = image.getBoundingClientRect();
        return {
            src: safeUrl(image.currentSrc || image.src),
            aboveFold: rect.top < innerHeight && rect.bottom > 0,
            loading: image.getAttribute("loading") || "auto",
            hasDimensions: image.hasAttribute("width") && image.hasAttribute("height"),
        };
    });
    const aboveFoldSources = new Set(
        images.filter((image) => image.aboveFold).map((image) => image.src)
    );
    const synchronousScripts = Array.from(document.scripts)
        .filter((script) => script.src && !script.defer && !script.async && script.type !== "module")
        .map((script) => safeUrl(script.src));
    const renderBlocking = Array.from(document.querySelectorAll('link[rel="stylesheet"]'))
        .filter((link) => !link.media || matchMedia(link.media).matches)
        .map((link) => safeUrl(link.href));

    return {
        ttfb_ms: navigation ? navigation.responseStart - navigation.startTime : null,
        dom_content_loaded_ms: navigation ? navigation.domContentLoadedEventEnd - navigation.startTime : null,
        load_ms: navigation ? navigation.loadEventEnd - navigation.startTime : null,
        lcp_ms: state.lcp ? state.lcp.time : null,
        cls: Number(state.cls || 0),
        document_bytes: navigation ? Number(navigation.decodedBodySize || 0) : 0,
        transferred_bytes: (navigation ? transferred(navigation) : 0)
            + resources.reduce((sum, entry) => sum + transferred(entry), 0),
        css_bytes: cssResources.reduce((sum, entry) => sum + transferred(entry), 0),
        js_bytes: jsResources.reduce((sum, entry) => sum + transferred(entry), 0),
        image_bytes: imageResources.reduce((sum, entry) => sum + transferred(entry), 0),
        request_count: resources.length + 1,
        dom_nodes: document.getElementsByTagName("*").length,
        largest_resource: largest.name ? {
            name: safeUrl(largest.name),
            bytes: transferred(largest),
        } : null,
        lcp_element: state.lcp ? state.lcp.element : null,
        lcp_resource: state.lcp ? state.lcp.url : null,
        render_blocking_resources: renderBlocking,
        css_requests: cssResources.length,
        js_requests: jsResources.length,
        missing_image_dimensions: images.filter((image) => !image.hasDimensions).map((image) => image.src),
        eager_below_fold_images: images.filter((image) =>
            !image.aboveFold
            && image.loading !== "lazy"
            && !aboveFoldSources.has(image.src)
        ).map((image) => image.src),
        lazy_above_fold_images: images.filter((image) => image.aboveFold && image.loading === "lazy").map((image) => image.src),
        synchronous_scripts: synchronousScripts,
        horizontal_overflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
        event_timing_max_ms: Math.max(0, ...(state.eventDurations || [])),
    };
}
"""


def _next_paint(page) -> float:
    return float(
        page.evaluate(
            """() => new Promise((resolve) => requestAnimationFrame(() =>
                requestAnimationFrame(() => resolve(performance.now()))))"""
        )
    )


def _perform_interactions(page, path: str) -> tuple[list[str], float | None]:
    interactions: list[str] = []
    latencies: list[float] = []

    def perform(name: str, action) -> None:
        started = float(page.evaluate("performance.now()"))
        action()
        completed = _next_paint(page)
        interactions.append(name)
        latencies.append(completed - started)

    menu = page.locator("[data-menu-toggle]")
    if menu.count() and menu.first.is_visible():
        perform("open mobile menu", menu.first.click)
        perform("close mobile menu", menu.first.click)

    if path == "/faq":
        summary = page.locator(".faq-list details summary").first
        if summary.count() and summary.is_visible():
            perform("open FAQ item", summary.click)

    if path == "/competitions":
        search = page.locator("[data-filter-search]")
        if search.count() and search.first.is_visible():
            perform("filter competition catalog", lambda: search.first.fill("Астана"))
            search.first.fill("")

    return interactions, max(latencies, default=None)


def _audit_once(
    browser,
    *,
    base_url: str,
    path: str,
    width: int,
    height: int,
    settle_ms: int,
    allow_third_party: bool,
) -> dict[str, Any]:
    context = browser.new_context(
        viewport={"width": width, "height": height},
        device_scale_factor=1,
        is_mobile=True,
        has_touch=True,
    )
    page = context.new_page()
    page.add_init_script(_OBSERVER_SCRIPT)
    console_errors: list[str] = []
    resource_errors: list[str] = []
    blocked_requests: list[str] = []
    base_origin = urlsplit(base_url)
    expected_origin = f"{base_origin.scheme}://{base_origin.netloc}"

    def record_console_message(message) -> None:
        if message.type != "error":
            return
        if message.text.startswith("Failed to load resource:"):
            resource_errors.append(message.text)
            return
        console_errors.append(message.text)

    page.on("console", record_console_message)
    page.on("pageerror", lambda error: console_errors.append(str(error)))

    if not allow_third_party:
        def restrict_request(route) -> None:
            request_url = urlsplit(route.request.url)
            request_origin = f"{request_url.scheme}://{request_url.netloc}"
            if request_origin == expected_origin:
                route.continue_()
                return
            blocked_requests.append(f"{request_origin}{request_url.path}")
            route.abort()

        page.route("**/*", restrict_request)

    try:
        response = page.goto(
            urljoin(f"{base_url}/", path.lstrip("/")),
            wait_until="load",
            timeout=30_000,
        )
        if response is None:
            raise AuditError(f"{path} did not return an HTTP response")
        page.wait_for_timeout(settle_ms)
        metrics = page.evaluate(_COLLECT_SCRIPT)
        interactions, interaction_latency = _perform_interactions(page, path)
        metrics.update(
            {
                "status": response.status,
                "interaction_latency_ms": interaction_latency,
                "interactions": interactions,
                "console_errors": console_errors,
                "resource_errors": resource_errors,
                "blocked_third_party_requests": sorted(set(blocked_requests)),
            }
        )
        return metrics
    finally:
        context.close()


def audit(
    *,
    base_url: str,
    routes: list[str],
    iterations: int,
    width: int,
    height: int,
    settle_ms: int,
    allow_third_party: bool,
) -> dict[str, Any]:
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise AuditError(
            "Playwright is not installed; install requirements-e2e.txt"
        ) from exc

    base_url = validate_base_url(base_url)
    routes = validate_routes(routes)
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                pages = []
                for path in routes:
                    runs = [
                        _audit_once(
                            browser,
                            base_url=base_url,
                            path=path,
                            width=width,
                            height=height,
                            settle_ms=settle_ms,
                            allow_third_party=allow_third_party,
                        )
                        for _ in range(iterations)
                    ]
                    pages.append(_aggregate_runs(path, runs))
            finally:
                browser.close()
    except PlaywrightError as exc:
        raise AuditError(
            "Chromium is unavailable; run `python -m playwright install chromium`"
        ) from exc

    return {
        "schema_version": 1,
        "kind": "artflow-playwright-lab-audit",
        "base_url": base_url,
        "viewport": {"width": width, "height": height},
        "iterations": iterations,
        "third_party_requests_allowed": allow_third_party,
        "pages": pages,
        "notes": [
            "Timing values are local Playwright laboratory measurements, not field Core Web Vitals.",
            "Interaction latency is measured to the next paint and is not field INP.",
        ],
    }


def compare(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    before_pages = {page["path"]: page for page in before.get("pages", [])}
    after_pages = {page["path"]: page for page in after.get("pages", [])}
    pages: list[dict[str, Any]] = []
    regressions: list[str] = []
    for path in sorted(before_pages.keys() & after_pages.keys()):
        before_page = before_pages[path]
        after_page = after_pages[path]
        deltas: dict[str, Any] = {}
        for metric in NUMERIC_METRICS:
            old = before_page.get(metric)
            new = after_page.get(metric)
            if old is None or new is None:
                continue
            delta = round(float(new) - float(old), 3)
            deltas[metric] = {
                "before": old,
                "after": new,
                "delta": delta,
                "percent": round(delta / float(old) * 100, 2) if old else None,
            }
            if (
                metric in REGRESSION_METRICS
                and float(old) > 0
                and float(new) > float(old) * (1 + REGRESSION_LIMIT)
            ):
                regressions.append(
                    f"{path}: {metric} increased by {deltas[metric]['percent']}%"
                )
        pages.append({"path": path, "metrics": deltas})
    return {
        "schema_version": 1,
        "kind": "artflow-playwright-lab-comparison",
        "before": before.get("base_url"),
        "after": after.get("base_url"),
        "pages": pages,
        "regressions": regressions,
        "regression_limit_percent": REGRESSION_LIMIT * 100,
    }


def _asset_totals(root: Path) -> dict[str, Any]:
    css_files = sorted((root / "static" / "css").glob("*.css"))
    js_files = sorted((root / "static" / "js").glob("*.js"))
    fallback = root / "static" / "images" / "artflow-logo-512.png"
    return {
        "css_files": len(css_files),
        "css_bytes": sum(path.stat().st_size for path in css_files),
        "javascript_files": len(js_files),
        "javascript_bytes": sum(path.stat().st_size for path in js_files),
        "fallback_image_bytes": fallback.stat().st_size if fallback.exists() else None,
    }


def structural_checks(
    *,
    root: Path = PROJECT_ROOT,
    report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    assets = _asset_totals(root)
    failures: list[str] = []
    warnings: list[str] = []

    for name in (
        "css_bytes",
        "javascript_bytes",
        "css_files",
        "javascript_files",
        "fallback_image_bytes",
    ):
        value = assets[name]
        if value is None or value > BUDGETS[name]:
            failures.append(f"{name}: {value!r} exceeds {BUDGETS[name]}")

    if report:
        for page in report.get("pages", []):
            path = page.get("path", "unknown")
            if page.get("status") != 200:
                failures.append(f"{path}: HTTP status is {page.get('status')}")
            if page.get("document_bytes", 0) > BUDGETS["html_bytes"]:
                failures.append(f"{path}: HTML exceeds {BUDGETS['html_bytes']} bytes")
            if page.get("request_count", 0) > BUDGETS["requests"]:
                failures.append(f"{path}: request count exceeds {BUDGETS['requests']}")
            if page.get("dom_nodes", 0) > BUDGETS["dom_nodes"]:
                failures.append(f"{path}: DOM exceeds {BUDGETS['dom_nodes']} nodes")
            if page.get("css_requests", 0) > BUDGETS["css_files"]:
                failures.append(f"{path}: too many CSS requests")
            if page.get("js_requests", 0) > BUDGETS["javascript_files"]:
                failures.append(f"{path}: too many JavaScript requests")
            for key in (
                "missing_image_dimensions",
                "synchronous_scripts",
                "console_errors",
            ):
                if page.get(key):
                    failures.append(f"{path}: {key}={page[key]!r}")
            if page.get("horizontal_overflow"):
                failures.append(f"{path}: horizontal overflow detected")
            if (
                page.get("lcp_resource")
                and page["lcp_resource"] in page.get("lazy_above_fold_images", [])
            ):
                failures.append(f"{path}: the LCP image is lazy-loaded")
            elif page.get("lazy_above_fold_images"):
                warnings.append(
                    f"{path}: review lazy above-fold images {page['lazy_above_fold_images']!r}"
                )
            if page.get("eager_below_fold_images"):
                warnings.append(
                    f"{path}: review eager below-fold images {page['eager_below_fold_images']!r}"
                )
            if page.get("resource_errors"):
                warnings.append(f"{path}: resource loading errors were observed")
            if page.get("lcp_ms") is not None and page["lcp_ms"] > 2500:
                warnings.append(f"{path}: lab LCP exceeds 2500 ms")
            if page.get("cls") is not None and page["cls"] > 0.1:
                warnings.append(f"{path}: lab CLS exceeds 0.1")

    return {
        "passed": not failures,
        "budgets": BUDGETS,
        "assets": assets,
        "failures": failures,
        "warnings": warnings,
    }


def _format_number(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def audit_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# ArtFlowWeb Playwright performance audit",
        "",
        f"- Base URL: `{report['base_url']}`",
        f"- Viewport: `{report['viewport']['width']}x{report['viewport']['height']}`",
        f"- Runs per page: `{report['iterations']}`",
        "- Timing type: local laboratory data, not field Core Web Vitals.",
        "",
        "| Path | Status | TTFB ms | DCL ms | Load ms | LCP ms | CLS | HTML B | Transfer B | Requests | DOM |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for page in report["pages"]:
        values = [
            f"`{page['path']}`",
            page["status"],
            page["ttfb_ms"],
            page["dom_content_loaded_ms"],
            page["load_ms"],
            page["lcp_ms"],
            page["cls"],
            page["document_bytes"],
            page["transferred_bytes"],
            page["request_count"],
            page["dom_nodes"],
        ]
        lines.append("| " + " | ".join(_format_number(value) for value in values) + " |")
    lines.extend(["", "## Page details", ""])
    for page in report["pages"]:
        largest = page.get("largest_resource") or {}
        lines.extend(
            [
                f"### `{page['path']}`",
                "",
                f"- CSS / JS / image transfer: `{page['css_bytes']}` / `{page['js_bytes']}` / `{page['image_bytes']}` bytes",
                f"- Largest resource: `{largest.get('name', 'n/a')}` ({largest.get('bytes', 'n/a')} bytes)",
                f"- LCP candidate: `{page.get('lcp_element') or 'n/a'}` / `{page.get('lcp_resource') or 'text'}`",
                f"- LCP candidate frequency: `{page.get('lcp_candidates', [])}`",
                f"- Render-blocking stylesheets: `{len(page.get('render_blocking_resources', []))}`",
                f"- Lab interaction-to-next-paint: `{_format_number(page.get('interaction_latency_ms'))}` ms",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def comparison_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# ArtFlowWeb performance comparison",
        "",
        "Values are local Playwright laboratory measurements.",
        "",
        "| Path | Metric | Before | After | Delta | Delta % |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for page in report["pages"]:
        for metric, values in page["metrics"].items():
            lines.append(
                "| "
                + " | ".join(
                    (
                        f"`{page['path']}`",
                        f"`{metric}`",
                        _format_number(values["before"]),
                        _format_number(values["after"]),
                        _format_number(values["delta"]),
                        _format_number(values["percent"]),
                    )
                )
                + " |"
            )
    if report.get("regressions"):
        lines.extend(["", "## Significant regressions", ""])
        lines.extend(f"- {item}" for item in report["regressions"])
    else:
        lines.extend(["", "No deterministic metric regressed by more than 10%."])
    return "\n".join(lines).rstrip() + "\n"


def _load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AuditError(f"cannot read JSON report {path}: {exc}") from exc


def _write_outputs(
    report: dict[str, Any],
    *,
    json_output: Path | None,
    markdown_output: Path | None,
    markdown: str,
) -> None:
    if json_output:
        json_output.parent.mkdir(parents=True, exist_ok=True)
        json_output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    if markdown_output:
        markdown_output.parent.mkdir(parents=True, exist_ok=True)
        markdown_output.write_text(markdown, encoding="utf-8")
    if not json_output and not markdown_output:
        print(markdown, end="")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Measure ArtFlowWeb with local Chromium without external analytics.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    audit_parser = commands.add_parser("audit", help="collect a Playwright lab report")
    audit_parser.add_argument("--base-url", required=True)
    audit_parser.add_argument("--routes", nargs="+", default=list(DEFAULT_ROUTES))
    audit_parser.add_argument("--iterations", type=int, default=3)
    audit_parser.add_argument("--width", type=int, default=375)
    audit_parser.add_argument("--height", type=int, default=812)
    audit_parser.add_argument("--settle-ms", type=int, default=750)
    audit_parser.add_argument("--allow-third-party", action="store_true")
    audit_parser.add_argument("--json-output", type=Path)
    audit_parser.add_argument("--markdown-output", type=Path)

    compare_parser = commands.add_parser("compare", help="compare two JSON audits")
    compare_parser.add_argument("before", type=Path)
    compare_parser.add_argument("after", type=Path)
    compare_parser.add_argument("--json-output", type=Path)
    compare_parser.add_argument("--markdown-output", type=Path)
    compare_parser.add_argument("--fail-on-regression", action="store_true")

    checks_parser = commands.add_parser(
        "structural-checks",
        help="check deterministic budgets, optionally using an audit report",
    )
    checks_parser.add_argument("--report", type=Path)
    checks_parser.add_argument("--root", type=Path, default=PROJECT_ROOT)
    checks_parser.add_argument("--json-output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        if arguments.command == "audit":
            if not 1 <= arguments.iterations <= 10:
                raise AuditError("iterations must be between 1 and 10")
            if arguments.width < 320 or arguments.height < 480:
                raise AuditError("viewport must be at least 320x480")
            report = audit(
                base_url=arguments.base_url,
                routes=arguments.routes,
                iterations=arguments.iterations,
                width=arguments.width,
                height=arguments.height,
                settle_ms=max(0, min(arguments.settle_ms, 5000)),
                allow_third_party=arguments.allow_third_party,
            )
            _write_outputs(
                report,
                json_output=arguments.json_output,
                markdown_output=arguments.markdown_output,
                markdown=audit_markdown(report),
            )
            return 0

        if arguments.command == "compare":
            report = compare(
                _load_json(arguments.before),
                _load_json(arguments.after),
            )
            _write_outputs(
                report,
                json_output=arguments.json_output,
                markdown_output=arguments.markdown_output,
                markdown=comparison_markdown(report),
            )
            return 1 if arguments.fail_on_regression and report["regressions"] else 0

        source_report = _load_json(arguments.report) if arguments.report else None
        report = structural_checks(root=arguments.root, report=source_report)
        rendered = json.dumps(report, ensure_ascii=False, indent=2)
        if arguments.json_output:
            arguments.json_output.parent.mkdir(parents=True, exist_ok=True)
            arguments.json_output.write_text(rendered + "\n", encoding="utf-8")
        else:
            print(rendered)
        return 0 if report["passed"] else 1
    except AuditError as exc:
        print(f"Performance audit failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
