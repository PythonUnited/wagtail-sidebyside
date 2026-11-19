"""The README screenshots, from the demo site (tests/demo.py).

    rm -f tests/demo.sqlite3 && uv run python -m tests.demo 8765
    uv run --with playwright python -m playwright install chromium
    uv run --with playwright python -m tests.screenshots

Writes docs/screenshots/*.png.
"""

from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://localhost:8765"
OUT = Path(__file__).parent.parent / "docs" / "screenshots"


def login(page):
    page.goto(f"{BASE}/cms/login/")
    page.fill("input[name=username]", "admin")
    page.fill("input[name=password]", "admin")
    page.click("button[type=submit]")
    page.wait_for_url(f"{BASE}/cms/")


def settle(page):
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(800)


with sync_playwright() as p:
    browser = p.chromium.launch()
    context = browser.new_context(viewport={"width": 1400, "height": 914})
    # The menu collapsed: more room for the screen itself.
    context.add_cookies(
        [{"name": "wagtail_sidebar_collapsed", "value": "1", "url": BASE}]
    )
    page = context.new_page()
    login(page)

    # Overview: pages and the footer snippet.
    page.set_viewport_size({"width": 1240, "height": 470})
    page.goto(f"{BASE}/cms/sidebyside/")
    settle(page)
    page.screenshot(path=OUT / "overview.png")

    # The source page editor with the translation bar.
    omelette = page.get_attribute("a:text('Omelette du fromage')", "href")
    page.set_viewport_size({"width": 1240, "height": 914})
    page.goto(f"{BASE}{omelette}")
    settle(page)
    # The top only, without the floating action bar at the bottom.
    page.screenshot(
        path=OUT / "source.png", clip={"x": 0, "y": 0, "width": 1240, "height": 300}
    )

    # The translation screen, the rich text just translated by AI.
    page.set_viewport_size({"width": 1400, "height": 914})
    page.goto(f"{BASE}{omelette}")
    page.click("a.sbs-bar__button:has-text('English')")
    settle(page)
    translate_url = page.url
    page.click("[data-path='body.r1'] button[name=ai]")
    settle(page)
    page.screenshot(path=OUT / "translate.png")

    # Saved, and the live preview next to it.
    page.click("button.action-save, button[name=action-save-draft], footer button")
    settle(page)
    page.click("[data-side-panel-toggle='preview']")
    page.wait_for_timeout(2500)
    page.screenshot(path=OUT / "preview.png")

    browser.close()
