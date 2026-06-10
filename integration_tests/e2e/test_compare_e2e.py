import pytest
from playwright.sync_api import Page, expect


@pytest.mark.e2e
def test_compare_page_loads(page: Page, server_url: str, screenshots_dir):
    page.goto(f"{server_url}/compare")
    page.wait_for_load_state("networkidle")
    expect(page).not_to_have_title("Error")
    page.screenshot(path=str(screenshots_dir / "compare_e2e.png"))
