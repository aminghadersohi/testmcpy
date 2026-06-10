import pytest
from playwright.sync_api import Page, expect


@pytest.mark.e2e
def test_auth_debugger_loads(page: Page, server_url: str, screenshots_dir):
    page.goto(f"{server_url}/auth-debugger")
    page.wait_for_load_state("networkidle")
    expect(page).not_to_have_title("Error")
    page.screenshot(path=str(screenshots_dir / "auth_e2e.png"))


@pytest.mark.e2e
def test_auth_debugger_has_form_fields(page: Page, server_url: str, screenshots_dir):
    page.goto(f"{server_url}/auth-debugger")
    page.wait_for_load_state("networkidle")
    inputs = page.locator("input, select, textarea").all()
    assert len(inputs) >= 1, "Expected form inputs"
