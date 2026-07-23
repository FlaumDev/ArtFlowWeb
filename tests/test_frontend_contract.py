from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")


def test_stylesheets_keep_the_original_cascade_order():
    base_template = _read("templates/base.html")
    stylesheet_paths = (
        "/css/base.css",
        "/css/components.css",
        "/css/pages.css",
        "/css/responsive.css",
    )

    positions = [base_template.index(path) for path in stylesheet_paths]

    assert positions == sorted(positions)
    assert "/css/style.css" not in base_template
    assert _read("static/css/base.css").count(":root") == 1
    assert sum(
        len(_read(f"static{path}" ).encode("utf-8"))
        for path in stylesheet_paths
    ) <= 75 * 1024


def test_mobile_navigation_and_sticky_cta_contracts():
    javascript = _read("static/js/main.js")

    assert "setMenuState(false, true)" in javascript
    assert "!menu.contains(event.target)" in javascript
    assert 'window.matchMedia("(min-width: 961px)")' in javascript
    assert 'typeof window.IntersectionObserver !== "function"' in javascript
    assert javascript.count("new IntersectionObserver(") == 1
    assert "requestAnimationFrame" in javascript
    assert "scheduleStickyCtaUpdate" in javascript


def test_dynamic_posters_have_intrinsic_dimensions():
    templates = (
        _read("templates/index.html"),
        _read("templates/components/competition_card.html"),
        _read("templates/competition_detail.html"),
    )

    for template in templates:
        assert 'width="1200"' in template
        assert 'height="900"' in template


def test_scroll_reveal_is_progressive_and_declarative():
    javascript = _read("static/js/main.js")
    pages_css = _read("static/css/pages.css")
    responsive_css = _read("static/css/responsive.css")
    templates = "\n".join(
        _read(path)
        for path in (
            "templates/index.html",
            "templates/competitions.html",
            "templates/competition_detail.html",
            "templates/faq.html",
        )
    )

    assert "data-reveal" in templates
    assert "data-reveal-delay" in templates
    assert 'document.querySelectorAll("[data-reveal]")' in javascript
    assert ".js-enabled [data-reveal]:not(.is-revealed)" in pages_css
    assert "translate: 0 18px" in pages_css
    assert "prefers-reduced-motion: reduce" in responsive_css
    assert ".reveal-item" not in pages_css


def test_optimized_logo_has_expected_dimensions_and_budget():
    logo_path = PROJECT_ROOT / "static/images/artflow-logo-512.png"
    logo = logo_path.read_bytes()

    assert logo[:8] == b"\x89PNG\r\n\x1a\n"
    assert int.from_bytes(logo[16:20], "big") == 512
    assert int.from_bytes(logo[20:24], "big") == 512
    assert len(logo) <= 70 * 1024
    assert "/images/artflow-logo-512.png" in _read("templates/base.html")


def test_primary_text_surface_meets_wcag_aa_contrast():
    def luminance(hex_color: str) -> float:
        channels = [
            int(hex_color[index:index + 2], 16) / 255
            for index in (0, 2, 4)
        ]
        linear = [
            channel / 12.92
            if channel <= 0.04045
            else ((channel + 0.055) / 1.055) ** 2.4
            for channel in channels
        ]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    ratio = (luminance("ffffff") + 0.05) / (luminance("bd202b") + 0.05)

    assert ratio >= 4.5
