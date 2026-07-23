from __future__ import annotations

import importlib.util
import re

import pytest


if importlib.util.find_spec("playwright") is not None:
    from playwright.sync_api import expect
else:
    def expect(_value):
        raise RuntimeError("Playwright is required for E2E assertions")


pytestmark = pytest.mark.e2e


def _javascript_errors(page):
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on(
        "console",
        lambda message: (
            errors.append(message.text)
            if message.type == "error"
            and "Failed to load resource" not in message.text
            else None
        ),
    )
    return errors


def test_home_and_mobile_menu(page, e2e_base_url):
    errors = _javascript_errors(page)
    page.set_viewport_size({"width": 375, "height": 812})
    response = page.goto(f"{e2e_base_url}/")

    assert response is not None and response.status == 200
    expect(page.locator("h1")).to_have_count(1)

    toggle = page.locator("[data-menu-toggle]")
    toggle.click()
    expect(toggle).to_have_attribute("aria-expanded", "true")
    expect(page.locator("body")).to_have_class(re.compile(r"\bmenu-open\b"))

    page.mouse.click(2, 500)
    expect(toggle).to_have_attribute("aria-expanded", "false")

    toggle.click()
    menu_home = page.locator("#site-menu").get_by_role(
        "link",
        name="Главная",
        exact=True,
    )
    menu_home.focus()
    page.keyboard.press("Escape")
    expect(toggle).to_be_focused()
    expect(toggle).to_have_attribute("aria-expanded", "false")

    toggle.click()
    page.set_viewport_size({"width": 1024, "height": 900})
    expect(page.locator("body")).not_to_have_class(re.compile(r"\bmenu-open\b"))
    assert errors == []


def test_navigation_and_filters(page, e2e_base_url):
    errors = _javascript_errors(page)
    page.goto(f"{e2e_base_url}/")
    page.locator("main").get_by_role(
        "link",
        name="Выбрать конкурс",
        exact=True,
    ).click()
    expect(page).to_have_url(f"{e2e_base_url}/competitions")

    cards = page.locator("[data-competition-card]")
    visible_cards = page.locator("[data-competition-card]:visible")
    expect(cards).to_have_count(3)
    search = page.get_by_placeholder(
        "Название, город или направление",
        exact=True,
    )

    search.fill("Караганда")
    expect(visible_cards).to_have_count(1)
    expect(page.locator("[data-filter-count]")).to_have_text("1")
    expect(visible_cards).to_have_class(re.compile(r"\bis-revealed\b"))

    search.fill("Современная хореография")
    expect(visible_cards).to_have_count(1)

    search.fill("")
    page.get_by_role("button", name="Завершённые", exact=True).click()
    expect(visible_cards).to_have_count(1)
    expect(page.get_by_text("Музыкальная палитра", exact=True)).to_be_visible()

    page.get_by_role("button", name="Сбросить", exact=True).click()
    expect(visible_cards).to_have_count(3)
    search.focus()
    page.keyboard.press("Tab")
    expect(page.get_by_role("button", name="Все", exact=True)).to_be_focused()
    assert errors == []


def test_catalog_without_javascript(browser, e2e_base_url):
    context = browser.new_context(java_script_enabled=False)
    page = context.new_page()
    try:
        page.goto(f"{e2e_base_url}/competitions")
        expect(page.locator("[data-competition-card]")).to_have_count(3)
        expect(page.get_by_text("Алматы", exact=True)).to_be_visible()
        expect(page.get_by_text("Караганда", exact=True)).to_be_visible()
        assert page.locator("[data-reveal]").first.evaluate(
            "element => getComputedStyle(element).opacity"
        ) == "1"
    finally:
        context.close()


def test_detail_deep_link_and_sticky_cta(page, e2e_base_url):
    errors = _javascript_errors(page)
    page.set_viewport_size({"width": 375, "height": 812})
    page.goto(f"{e2e_base_url}/competitions/7")

    primary = page.locator(".event-actions").get_by_role(
        "link",
        name="Подать заявку в Telegram",
        exact=True,
    )
    expect(primary).to_have_attribute(
        "href",
        "https://t.me/ArtFlowBot?start=competition_7",
    )
    sticky = page.locator("[data-sticky-cta]")
    expect(sticky).not_to_be_visible()

    primary.evaluate(
        """element => window.scrollTo(
            0,
            element.getBoundingClientRect().bottom + window.scrollY + 1
        )"""
    )
    expect(sticky).to_be_visible()
    page.evaluate(
        """() => {
            document.documentElement.style.scrollBehavior = 'auto';
            window.scrollTo(0, document.body.scrollHeight);
        }"""
    )
    expect(sticky).to_be_visible()
    footer_bottom = page.locator(".site-footer").evaluate(
        "element => element.getBoundingClientRect().bottom"
    )
    sticky_top = sticky.evaluate("element => element.getBoundingClientRect().top")
    assert footer_bottom <= sticky_top

    page.evaluate("window.scrollTo(0, 0)")
    expect(sticky).not_to_be_visible()

    page.goto(f"{e2e_base_url}/competitions/8")
    expect(page.locator("[data-sticky-cta]")).to_have_count(0)
    expect(
        page.get_by_role("link", name="Посмотреть другие конкурсы", exact=True)
    ).to_be_visible()
    assert "competition_8" not in page.content()
    assert errors == []


def test_faq_and_broken_poster_fallback(page, e2e_base_url):
    errors = _javascript_errors(page)
    page.goto(f"{e2e_base_url}/faq")
    question = page.get_by_text("Как подать заявку?", exact=True)
    question.click()
    expect(
        page.get_by_text(
            "Выберите конкурс и перейдите в Telegram по кнопке заявки.",
            exact=True,
        )
    ).to_be_visible()

    page.goto(f"{e2e_base_url}/competitions")
    broken_card = page.locator(
        "[data-competition-card]",
        has_text="Большой творческий конкурс ArtFlow",
    )
    expect(broken_card.locator("[data-poster-placeholder]")).to_be_visible()
    expect(broken_card.locator("[data-poster-image]")).not_to_have_class(
        re.compile(r"\bis-loaded\b")
    )
    assert broken_card.locator("[data-poster-image]").evaluate(
        "element => getComputedStyle(element).opacity"
    ) == "0"

    working_card = page.locator(
        "[data-competition-card]",
        has_text="Музыкальная палитра",
    )
    expect(working_card.locator("[data-poster-image]")).to_have_class(
        re.compile(r"\bis-loaded\b")
    )
    expect(working_card.locator("[data-poster-placeholder]")).to_be_hidden()
    assert working_card.locator("[data-poster-image]").evaluate(
        "element => element.complete && element.naturalWidth > 0"
    )
    assert errors == []


def test_scroll_reveal_before_and_after_intersection(page, e2e_base_url):
    page.set_viewport_size({"width": 375, "height": 640})
    page.goto(f"{e2e_base_url}/")

    expect(page.locator(".hero-copy")).to_have_class(re.compile(r"\bis-revealed\b"))
    target = page.locator(".about-copy")
    expect(target).not_to_have_class(re.compile(r"\bis-revealed\b"))
    target.scroll_into_view_if_needed()
    expect(target).to_have_class(re.compile(r"\bis-revealed\b"))


def test_reveal_respects_reduced_motion(browser, e2e_base_url):
    context = browser.new_context(reduced_motion="reduce")
    page = context.new_page()
    try:
        page.goto(f"{e2e_base_url}/")
        expect(page.locator("[data-reveal]:not(.is-revealed)")).to_have_count(0)
        assert page.locator("[data-reveal]").first.evaluate(
            "element => getComputedStyle(element).transitionDuration"
        ) == "0s"
    finally:
        context.close()


def test_reveal_without_intersection_observer(browser, e2e_base_url):
    context = browser.new_context()
    context.add_init_script(
        "Object.defineProperty(window, 'IntersectionObserver', "
        "{ configurable: true, value: undefined });"
    )
    page = context.new_page()
    try:
        page.goto(f"{e2e_base_url}/competitions")
        expect(page.locator("[data-reveal]:not(.is-revealed)")).to_have_count(0)
        expect(page.locator("[data-competition-card]")).to_have_count(3)
    finally:
        context.close()


@pytest.mark.parametrize("width", [320, 375, 768, 1440])
@pytest.mark.parametrize(
    "path",
    ["/", "/competitions", "/competitions/7", "/faq", "/not-found"],
)
def test_no_horizontal_overflow(page, e2e_base_url, path, width):
    page.set_viewport_size({"width": width, "height": 900})
    page.goto(f"{e2e_base_url}{path}")
    metrics = page.evaluate(
        """() => ({
            clientWidth: document.documentElement.clientWidth,
            scrollWidth: document.documentElement.scrollWidth,
            bodyScrollWidth: document.body.scrollWidth,
        })"""
    )
    assert metrics["scrollWidth"] <= metrics["clientWidth"]
    assert metrics["bodyScrollWidth"] <= metrics["clientWidth"]


def test_error_pages(page, e2e_base_url):
    expected = [
        ("/not-found", 404, "Похоже, здесь уже закончилась программа"),
        ("/__e2e/500", 500, "Эта страница временно недоступна"),
        ("/__e2e/503", 503, "Конкурсы временно недоступны"),
    ]
    for path, status, heading in expected:
        response = page.goto(f"{e2e_base_url}{path}")
        assert response is not None and response.status == status
        expect(page.locator("h1")).to_have_count(1)
        expect(page.get_by_role("heading", name=heading, exact=True)).to_be_visible()


@pytest.mark.parametrize("path", ["/", "/competitions", "/competitions/7", "/faq"])
def test_accessibility_basics(page, e2e_base_url, path):
    page.set_viewport_size({"width": 375, "height": 812})
    page.goto(f"{e2e_base_url}{path}")
    audit = page.evaluate(
        """() => {
            const headings = Array.from(document.querySelectorAll('h1, h2, h3'));
            const levels = headings.map((item) => Number(item.tagName.slice(1)));
            const headingJump = levels.some((level, index) => (
                index > 0 && level - levels[index - 1] > 1
            ));
            const emptyLinks = Array.from(document.querySelectorAll('a')).filter((link) => {
                const imageAlt = link.querySelector('img')?.getAttribute('alt') || '';
                return !link.textContent.trim() && !link.getAttribute('aria-label') && !imageAlt;
            }).length;
            const imagesWithoutAlt = Array.from(document.images).filter(
                (image) => !image.hasAttribute('alt')
            ).length;
            const unlabeledControls = Array.from(
                document.querySelectorAll('input, select, textarea')
            ).filter((control) => (
                !control.labels?.length
                && !control.getAttribute('aria-label')
                && !control.getAttribute('aria-labelledby')
            )).length;
            return {
                h1Count: document.querySelectorAll('h1').length,
                headingJump,
                emptyLinks,
                imagesWithoutAlt,
                unlabeledControls,
            };
        }"""
    )
    assert audit == {
        "h1Count": 1,
        "headingJump": False,
        "emptyLinks": 0,
        "imagesWithoutAlt": 0,
        "unlabeledControls": 0,
    }


def test_primary_color_contrast():
    def relative_luminance(hex_color):
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

    white = relative_luminance("ffffff")
    primary = relative_luminance("bd202b")
    contrast = (white + 0.05) / (primary + 0.05)

    assert contrast >= 4.5
