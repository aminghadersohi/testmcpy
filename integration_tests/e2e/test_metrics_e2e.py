import pytest
from playwright.sync_api import Page, expect


@pytest.mark.e2e
def test_metrics_page_loads(page: Page, server_url: str, screenshots_dir):
    page.goto(f"{server_url}/metrics")
    page.wait_for_load_state("networkidle")
    expect(page).not_to_have_title("Error")
    page.screenshot(path=str(screenshots_dir / "metrics_e2e.png"))


@pytest.mark.e2e
def test_metrics_has_content(page: Page, server_url: str, screenshots_dir):
    page.goto(f"{server_url}/metrics")
    page.wait_for_load_state("networkidle")
    page.wait_for_selector("h1, h2, svg, .grid", timeout=5000)
    page.screenshot(path=str(screenshots_dir / "metrics_content.png"))
