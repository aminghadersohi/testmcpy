import pytest
from playwright.sync_api import Page, expect


@pytest.mark.e2e
def test_security_page_loads(page: Page, server_url: str, screenshots_dir):
    page.goto(f"{server_url}/security")
    page.wait_for_load_state("networkidle")
    expect(page).not_to_have_title("Error")
    page.screenshot(path=str(screenshots_dir / "security_e2e.png"))
