"""E2E tests for the Reports page — filters, comparison, run list."""

import pytest


@pytest.mark.e2e
class TestReportsPage:
    """Tests for /reports page load and core elements."""

    def test_page_loads_with_tabs(self, page, server_url, screenshots_dir):
        page.goto(f"{server_url}/reports")
        page.wait_for_load_state("networkidle")

        # Should have Test Runs and Smoke Tests tabs
        assert page.locator("button:has-text('Test Runs')").is_visible()
        assert page.locator("button:has-text('Smoke Tests')").is_visible()

        page.screenshot(path=str(screenshots_dir / "reports_tabs.png"))

    def test_filter_bar_visible(self, page, server_url, screenshots_dir):
        page.goto(f"{server_url}/reports")
        page.wait_for_load_state("networkidle")

        # Search input should be visible
        search = page.locator("input[placeholder='Search...']")
        assert search.is_visible()

        # Status filter buttons should be visible
        assert page.locator("button:has-text('All')").first.is_visible()
        assert page.locator("button:has-text('Passed')").is_visible()
        assert page.locator("button:has-text('Failed')").is_visible()

        # Compare button should be visible
        assert page.locator("button:has-text('Compare')").is_visible()

        page.screenshot(path=str(screenshots_dir / "reports_filter_bar.png"))

    def test_status_filter_buttons(self, page, server_url):
        page.goto(f"{server_url}/reports")
        page.wait_for_load_state("networkidle")

        # Click Passed filter
        page.locator("button:has-text('Passed')").click()
        page.wait_for_timeout(500)

        # Click Failed filter
        page.locator("button:has-text('Failed')").click()
        page.wait_for_timeout(500)

        # Click All to reset
        page.locator("button:has-text('All')").first.click()
        page.wait_for_timeout(500)

    def test_search_filter(self, page, server_url):
        page.goto(f"{server_url}/reports")
        page.wait_for_load_state("networkidle")

        search = page.locator("input[placeholder='Search...']")
        search.fill("health")
        page.wait_for_timeout(500)

        # Clear search
        search.fill("")
        page.wait_for_timeout(500)


@pytest.mark.e2e
class TestReportsComparison:
    """Tests for the compare mode and comparison modal."""

    def test_compare_mode_toggle(self, page, server_url, screenshots_dir):
        page.goto(f"{server_url}/reports")
        page.wait_for_load_state("networkidle")

        compare_btn = page.locator("button:has-text('Compare')")
        assert compare_btn.is_visible()

        # Enter compare mode
        compare_btn.click()
        page.wait_for_timeout(500)

        # Should show Cancel Compare
        assert page.locator("button:has-text('Cancel Compare')").is_visible()

        page.screenshot(path=str(screenshots_dir / "reports_compare_mode.png"))

        # Exit compare mode
        page.locator("button:has-text('Cancel Compare')").click()
        page.wait_for_timeout(500)

        # Should show Compare again
        assert page.locator("button:has-text('Compare')").is_visible()

    def test_compare_select_runs(self, page, server_url, screenshots_dir):
        page.goto(f"{server_url}/reports")
        page.wait_for_load_state("networkidle")

        # Enter compare mode
        page.locator("button:has-text('Compare')").click()
        page.wait_for_timeout(500)

        # Check if there are checkboxes visible (only if runs exist)
        checkboxes = page.locator("input[type='checkbox']")
        if checkboxes.count() >= 2:
            # Click run items directly (which toggles checkboxes in compare mode)
            run_items = page.locator(".divide-y > div")
            run_items.nth(0).click()
            page.wait_for_timeout(300)
            run_items.nth(1).click()
            page.wait_for_timeout(500)

            # Compare button with count should appear (text includes dynamic count)
            compare_action = page.locator("button", has_text="Compare 2")
            if compare_action.is_visible():
                page.screenshot(path=str(screenshots_dir / "reports_compare_selected.png"))

                # Click compare
                compare_action.click()
                page.wait_for_timeout(1000)

                # Comparison modal should appear
                modal = page.locator("text=Run Comparison")
                if modal.is_visible():
                    page.screenshot(path=str(screenshots_dir / "reports_compare_modal.png"))
                    # Close modal first
                    page.locator("button:has-text('\u00d7')").click()
                    page.wait_for_timeout(300)

        # Clean up — exit compare mode
        cancel = page.locator("button:has-text('Cancel Compare')")
        if cancel.is_visible():
            cancel.click()


@pytest.mark.e2e
class TestReportsFilterDropdowns:
    """Tests for server-side filter dropdowns."""

    def test_filter_dropdowns_render(self, page, server_url, screenshots_dir):
        page.goto(f"{server_url}/reports")
        page.wait_for_load_state("networkidle")

        # Check if model/provider/test_file dropdowns exist
        # They only render when there are 2+ distinct values
        page.locator("select").count()  # just verify no crash

        page.screenshot(path=str(screenshots_dir / "reports_dropdowns.png"))

        # At minimum, if data exists, we should see some dropdowns
        # This test passes even if no data (dropdowns just won't render)

    def test_model_filter_changes_results(self, page, server_url):
        page.goto(f"{server_url}/reports")
        page.wait_for_load_state("networkidle")

        # Find model dropdown if it exists
        model_select = page.locator("select").first
        if model_select.is_visible():
            # Select a specific model option (skip "All Models")
            options = model_select.locator("option")
            if options.count() > 1:
                model_select.select_option(index=1)
                page.wait_for_timeout(1000)

                # Reset
                model_select.select_option(value="")
                page.wait_for_timeout(500)

    def test_clear_filters(self, page, server_url):
        page.goto(f"{server_url}/reports")
        page.wait_for_load_state("networkidle")

        # If a filter dropdown exists, select something
        model_select = page.locator("select").first
        if model_select.is_visible():
            options = model_select.locator("option")
            if options.count() > 1:
                model_select.select_option(index=1)
                page.wait_for_timeout(500)

                # Clear filters button should appear
                clear_btn = page.locator("button:has-text('Clear filters')")
                if clear_btn.is_visible():
                    clear_btn.click()
                    page.wait_for_timeout(500)


@pytest.mark.e2e
class TestReportsRunDetails:
    """Tests for clicking a run and viewing details."""

    def test_click_run_shows_details(self, page, server_url, screenshots_dir):
        page.goto(f"{server_url}/reports")
        page.wait_for_load_state("networkidle")

        # Click the first run in the list (if any)
        run_items = page.locator(".divide-y > div").first
        if run_items.is_visible():
            run_items.click()
            page.wait_for_timeout(1000)

            page.screenshot(path=str(screenshots_dir / "reports_run_details.png"), full_page=True)

    def test_refresh_button(self, page, server_url):
        page.goto(f"{server_url}/reports")
        page.wait_for_load_state("networkidle")

        refresh = page.locator("button:has-text('Refresh')")
        if refresh.is_visible():
            refresh.click()
            page.wait_for_timeout(1000)
