import pytest
from playwright.sync_api import Page, expect


@pytest.mark.e2e
def test_chat_renders_input(page: Page, server_url: str, screenshots_dir):
    page.goto(f"{server_url}/chat")
    page.wait_for_load_state("networkidle")
    expect(page).not_to_have_title("Error")
    page.screenshot(path=str(screenshots_dir / "chat_welcome_e2e.png"))
    textarea = page.locator("textarea").first
    expect(textarea).to_be_visible()


@pytest.mark.e2e
def test_chat_input_accepts_text(page: Page, server_url: str, screenshots_dir):
    page.goto(f"{server_url}/chat")
    page.wait_for_load_state("networkidle")
    textarea = page.locator("textarea").first
    textarea.fill("Hello")
    assert textarea.input_value() == "Hello"
    page.screenshot(path=str(screenshots_dir / "chat_typed_e2e.png"))
