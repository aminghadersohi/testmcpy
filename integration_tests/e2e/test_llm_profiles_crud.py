"""Destructive-but-cleaned-up LLM profile browser workflow."""

import uuid

import httpx
import pytest


@pytest.mark.e2e
def test_llm_profile_assistant_round_trip_and_duplicate_guard(page, server_url):
    profile_id = f"e2e-{uuid.uuid4().hex[:8]}"
    profile_name = "E2E Assistant Profile"
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))

    try:
        page.goto(f"{server_url}/llm-profiles")
        page.wait_for_load_state("networkidle")

        page.get_by_role("button", name="Add Profile", exact=True).click()
        page.get_by_label("Profile ID").fill(profile_id)
        page.get_by_label("Profile Name").fill(profile_name)
        page.get_by_label("Description").fill("Browser round-trip regression")
        page.get_by_role("button", name="Create Profile").click()
        page.get_by_text(profile_name, exact=True).wait_for()

        card = (
            page.locator("div.rounded-lg")
            .filter(has=page.get_by_text(profile_id, exact=True))
            .first
        )
        card.get_by_role("button", name="Add Provider", exact=True).click()
        page.get_by_label("Provider", exact=True).select_option("assistant")
        page.get_by_label("Model").fill("assistant-model")
        page.get_by_label("Display Name").fill("Assistant Provider")
        page.get_by_label("Workspace Hash").fill("workspace-e2e")
        page.get_by_label("Domain").fill("example.test")
        page.get_by_label("Auth API URL").fill("https://example.test/auth")
        page.get_by_label("API Token").fill("literal-token-e2e")
        page.get_by_label("API Secret").fill("literal-secret-e2e")
        page.get_by_label("Conversations Path").fill("/conversations")
        page.get_by_label("Completions Path").fill("/completions")
        page.get_by_label("Set as default provider").check()
        page.get_by_role("button", name="Save Provider").click()
        page.get_by_text("Assistant Provider", exact=True).wait_for()

        # A profile metadata save exercises the full provider-array round trip.
        card = (
            page.locator("div.rounded-lg")
            .filter(has=page.get_by_text(profile_id, exact=True))
            .first
        )
        card.get_by_title("Edit profile").click()
        page.get_by_label("Description").fill("Updated without losing assistant auth")
        page.get_by_role("button", name="Save", exact=True).click()

        listed = httpx.get(f"{server_url}/api/llm/profiles", timeout=5).json()
        profile = next(item for item in listed["profiles"] if item["profile_id"] == profile_id)
        provider = profile["providers"][0]
        assert provider["provider"] == "assistant"
        assert provider["api_token"] == "***"
        assert provider["api_secret"] == "***"
        assert provider["workspace_hash"] == "workspace-e2e"
        assert provider["conversations_path"] == "/conversations"

        # Duplicate creation must leave the modal open and preserve the profile.
        page.get_by_role("button", name="Add Profile", exact=True).click()
        page.get_by_label("Profile ID").fill(profile_id)
        page.get_by_label("Profile Name").fill("Must Not Replace")
        page.get_by_role("button", name="Create Profile").click()
        page.get_by_text("already exists", exact=False).wait_for()
        assert page.get_by_role("heading", name="New LLM Profile").is_visible()

        listed = httpx.get(f"{server_url}/api/llm/profiles", timeout=5).json()
        profile = next(item for item in listed["profiles"] if item["profile_id"] == profile_id)
        assert profile["name"] == profile_name
        assert len(profile["providers"]) == 1
        assert errors == []
    finally:
        httpx.delete(f"{server_url}/api/llm/profiles/{profile_id}", timeout=5)


@pytest.mark.e2e
def test_llm_profile_actions_fit_mobile_viewport(page, server_url):
    profile_id = f"mobile-{uuid.uuid4().hex[:8]}"
    created = httpx.post(
        f"{server_url}/api/llm/profiles/{profile_id}",
        json={
            "name": "Mobile Actions",
            "providers": [
                {
                    "name": f"Local provider {index}",
                    "provider": "ollama",
                    "model": f"local-model-{index}",
                    "base_url": "http://127.0.0.1:11434",
                    "default": index == 0,
                }
                for index in range(3)
            ],
        },
        timeout=5,
    )
    assert created.status_code == 200

    try:
        page.set_viewport_size({"width": 320, "height": 720})
        page.goto(f"{server_url}/llm-profiles")
        page.wait_for_load_state("networkidle")
        card = (
            page.locator("div.rounded-lg")
            .filter(has=page.get_by_text(profile_id, exact=True))
            .first
        )

        controls = [
            page.get_by_role("button", name="Refresh", exact=True),
            page.get_by_role("button", name="Add Provider (Wizard)", exact=True),
            page.get_by_role("button", name="Add Profile", exact=True),
            card.get_by_title("Hide providers"),
            card.get_by_role("button", name="Add Provider", exact=True),
            *card.get_by_title("Remove provider").all(),
        ]
        for control in controls:
            box = control.bounding_box()
            assert box is not None
            assert box["x"] >= 0
            assert box["x"] + box["width"] <= 320
    finally:
        httpx.delete(f"{server_url}/api/llm/profiles/{profile_id}", timeout=5)


@pytest.mark.e2e
def test_llm_profile_validation_error_keeps_page_mounted(page, server_url):
    def reject_create(route):
        route.fulfill(
            status=422,
            content_type="application/json",
            body='{"detail":[{"msg":"Synthetic validation failure"}]}',
        )

    page.route("**/api/llm/profiles/e2e-validation", reject_create)
    page.goto(f"{server_url}/llm-profiles")
    page.wait_for_load_state("networkidle")
    page.get_by_role("button", name="Add Profile", exact=True).click()
    page.get_by_label("Profile ID").fill("e2e-validation")
    page.get_by_label("Profile Name").fill("Validation")
    page.get_by_role("button", name="Create Profile").click()

    page.get_by_text("Synthetic validation failure", exact=True).wait_for()
    assert page.get_by_role("heading", name="New LLM Profile").is_visible()
    assert page.get_by_role("heading", name="LLM Profiles", exact=True).is_visible()
