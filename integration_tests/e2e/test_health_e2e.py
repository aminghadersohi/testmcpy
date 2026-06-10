import pytest
from playwright.sync_api import Page, expect


@pytest.mark.e2e
def test_health_page_loads(page: Page, server_url: str, screenshots_dir):
    # The MCP Health page is at /mcp-health (from App.jsx routes)
    page.goto(f"{server_url}/mcp-health")
    page.wait_for_load_state("networkidle")
    expect(page).not_to_have_title("Error")
    page.screenshot(path=str(screenshots_dir / "health_e2e.png"))
