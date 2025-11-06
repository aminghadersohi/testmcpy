"""
Simple, working TUI for testmcpy.
"""

from textual.app import App, ComposeResult
from textual.containers import Container, Vertical, Horizontal
from textual.widgets import Header, Footer, Static, Button, Label
from textual.binding import Binding


class SimpleHome(Static):
    """Simple home screen with actual working buttons."""

    def compose(self) -> ComposeResult:
        """Create the home screen layout."""
        yield Label("🧪 testmcpy - MCP Testing Framework", id="title")
        yield Label("", id="spacer1")
        yield Label("Choose an action:", id="subtitle")
        yield Label("", id="spacer2")

        with Vertical(id="menu"):
            yield Button("🔍 Explorer - Browse MCP Tools", id="explorer", variant="primary")
            yield Button("🧪 Tests - Run & Manage Tests", id="tests", variant="primary")
            yield Button("💬 Chat - Interactive MCP Chat", id="chat", variant="primary")
            yield Button("⚙️  Profiles - Manage MCP Profiles", id="profiles", variant="primary")
            yield Button("❌ Quit", id="quit", variant="error")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        button_id = event.button.id

        if button_id == "quit":
            self.app.exit()
        elif button_id == "explorer":
            self.app.push_screen("explorer")
        elif button_id == "tests":
            self.app.push_screen("tests")
        elif button_id == "chat":
            self.app.push_screen("chat")
        elif button_id == "profiles":
            self.app.push_screen("profiles")


class ExplorerScreen(Container):
    """Simple explorer screen."""

    def compose(self) -> ComposeResult:
        yield Label("🔍 MCP Explorer")
        yield Label("")
        yield Label("This will show MCP tools, resources, and prompts.")
        yield Label("Press ESC or q to go back")
        yield Label("")
        yield Button("← Back to Home", id="back")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle back button."""
        if event.button.id == "back":
            self.app.pop_screen()

    def on_key(self, event) -> None:
        """Handle key presses."""
        if event.key in ("escape", "q"):
            self.app.pop_screen()


class TestsScreen(Container):
    """Simple tests screen."""

    def compose(self) -> ComposeResult:
        yield Label("🧪 Test Runner")
        yield Label("")
        yield Label("This will show and run your MCP tests.")
        yield Label("Press ESC or q to go back")
        yield Label("")
        yield Button("← Back to Home", id="back")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle back button."""
        if event.button.id == "back":
            self.app.pop_screen()

    def on_key(self, event) -> None:
        """Handle key presses."""
        if event.key in ("escape", "q"):
            self.app.pop_screen()


class ChatScreen(Container):
    """Simple chat screen."""

    def compose(self) -> ComposeResult:
        yield Label("💬 Interactive Chat")
        yield Label("")
        yield Label("This will be an interactive chat with MCP tools.")
        yield Label("Press ESC or q to go back")
        yield Label("")
        yield Button("← Back to Home", id="back")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle back button."""
        if event.button.id == "back":
            self.app.pop_screen()

    def on_key(self, event) -> None:
        """Handle key presses."""
        if event.key in ("escape", "q"):
            self.app.pop_screen()


class ProfilesScreen(Container):
    """Simple profiles screen."""

    def compose(self) -> ComposeResult:
        yield Label("⚙️  MCP Profiles")
        yield Label("")
        yield Label("This will show your MCP profiles from .mcp_services.yaml")
        yield Label("Press ESC or q to go back")
        yield Label("")
        yield Button("← Back to Home", id="back")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle back button."""
        if event.button.id == "back":
            self.app.pop_screen()

    def on_key(self, event) -> None:
        """Handle key presses."""
        if event.key in ("escape", "q"):
            self.app.pop_screen()


class TestMCPyApp(App):
    """Simple, working testmcpy TUI."""

    CSS = """
    Screen {
        align: center middle;
    }

    #title {
        text-align: center;
        text-style: bold;
        color: $accent;
        width: 100%;
        margin: 1;
    }

    #subtitle {
        text-align: center;
        width: 100%;
        margin: 1;
    }

    #spacer1, #spacer2 {
        height: 1;
    }

    #menu {
        width: 60;
        margin: 2 auto;
    }

    Button {
        width: 100%;
        margin: 1 0;
    }

    Container {
        width: 80;
        height: auto;
        padding: 2;
        margin: 2 auto;
    }

    Label {
        width: 100%;
        margin: 1 0;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit", show=True, priority=True),
        Binding("escape", "pop_screen", "Back", show=True),
    ]

    SCREENS = {
        "home": SimpleHome,
        "explorer": ExplorerScreen,
        "tests": TestsScreen,
        "chat": ChatScreen,
        "profiles": ProfilesScreen,
    }

    TITLE = "testmcpy"
    SUB_TITLE = "MCP Testing Framework"

    def __init__(self, profile: str | None = None, **kwargs):
        super().__init__(**kwargs)
        self.profile = profile

    def on_mount(self) -> None:
        """Show home screen on start."""
        if self.profile:
            self.sub_title = f"Profile: {self.profile}"
        self.push_screen("home")

    def compose(self) -> ComposeResult:
        """Compose app with header and footer."""
        yield Header()
        yield Footer()

    def action_pop_screen(self) -> None:
        """Go back to previous screen."""
        if len(self.screen_stack) > 1:
            self.pop_screen()


def run_tui(profile: str | None = None, enable_auto_refresh: bool = False):
    """
    Launch the main TUI dashboard.

    Args:
        profile: MCP profile to use
        enable_auto_refresh: Enable auto-refresh (not implemented yet)
    """
    app = TestMCPyApp(profile=profile)
    app.run()


def launch_chat(
    profile: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    mcp_url: str | None = None,
):
    """
    Launch the chat interface directly.

    Args:
        profile: MCP profile ID
        provider: LLM provider
        model: Model name
        mcp_url: MCP service URL
    """
    # For now, just launch the main app and go to chat
    app = TestMCPyApp(profile=profile)
    app.run()
