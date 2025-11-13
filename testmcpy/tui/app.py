"""
Simple, working TUI for testmcpy.
"""

import traceback
from textual.app import App, ComposeResult
from textual.containers import Container, Vertical, Horizontal
from textual.widgets import Header, Footer, Static, Button, Label
from textual.binding import Binding
from textual.screen import ModalScreen, Screen

from testmcpy.tui.screens.auth_debugger import AuthDebuggerScreen


class ErrorModal(ModalScreen):
    """Modal screen to display error messages."""

    DEFAULT_CSS = """
    ErrorModal {
        align: center middle;
    }

    #error-dialog {
        width: 60;
        height: auto;
        max-height: 30;
        background: $panel;
        border: thick $error;
        padding: 1 2;
    }

    #error-title {
        width: 100%;
        content-align: center middle;
        text-style: bold;
        color: $error;
        padding: 1 0;
    }

    #error-message {
        width: 100%;
        height: auto;
        max-height: 15;
        overflow-y: auto;
        padding: 1 0;
    }

    #error-buttons {
        width: 100%;
        height: auto;
        align: center middle;
        padding: 1 0;
    }
    """

    def __init__(self, error_message: str, title: str = "Error"):
        super().__init__()
        self.error_message = error_message
        self.title = title

    def compose(self) -> ComposeResult:
        with Container(id="error-dialog"):
            yield Label(self.title, id="error-title")
            yield Label(self.error_message, id="error-message")
            with Horizontal(id="error-buttons"):
                yield Button("Close", variant="error", id="close")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press."""
        if event.button.id == "close":
            self.app.pop_screen()

    def on_key(self, event) -> None:
        """Handle key presses."""
        if event.key in ("escape", "enter"):
            self.app.pop_screen()


class SimpleHome(Screen):
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
            yield Button("🔐 Auth Debugger - Debug Authentication", id="auth_debugger", variant="primary")
            yield Button("⚙️  Profiles - Manage MCP Profiles", id="profiles", variant="primary")
            yield Button("❌ Quit", id="quit", variant="error")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses with error handling."""
        button_id = event.button.id

        try:
            if button_id == "quit":
                self.app.exit()
            elif button_id == "explorer":
                self.app.push_screen("explorer")
            elif button_id == "tests":
                self.app.push_screen("tests")
            elif button_id == "chat":
                self.app.push_screen("chat")
            elif button_id == "auth_debugger":
                self.app.push_screen("auth_debugger")
            elif button_id == "profiles":
                self.app.push_screen("profiles")
        except Exception as e:
            error_msg = f"Failed to navigate to {button_id}: {str(e)}\n\n{traceback.format_exc()}"
            self.app.push_screen(ErrorModal(error_msg, title="Navigation Error"))


class ExplorerScreen(Screen):
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


class TestsScreen(Screen):
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


class ChatScreen(Screen):
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


class ProfilesScreen(Screen):
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
    """Simple, working testmcpy TUI with error recovery."""

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
        margin: 2 0;
    }

    Button {
        width: 100%;
        margin: 1 0;
    }

    Container {
        width: 80;
        height: auto;
        padding: 2;
        margin: 2 0;
    }

    Label {
        width: 100%;
        margin: 1 0;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit", show=True, priority=True),
        Binding("escape", "pop_screen", "Back", show=True),
        Binding("a", "auth_debugger", "Auth Debug", show=True),
    ]

    SCREENS = {
        "home": SimpleHome,
        "explorer": ExplorerScreen,
        "tests": TestsScreen,
        "chat": ChatScreen,
        "auth_debugger": AuthDebuggerScreen,
        "profiles": ProfilesScreen,
    }

    TITLE = "testmcpy"
    SUB_TITLE = "MCP Testing Framework"

    def __init__(self, profile: str | None = None, **kwargs):
        super().__init__(**kwargs)
        self.profile = profile

    def on_mount(self) -> None:
        """Show home screen on start with error handling."""
        try:
            if self.profile:
                self.sub_title = f"Profile: {self.profile}"
            self.push_screen("home")
        except Exception as e:
            error_msg = f"Failed to initialize app: {str(e)}\n\n{traceback.format_exc()}"
            self.push_screen(ErrorModal(error_msg, title="Initialization Error"))

    def compose(self) -> ComposeResult:
        """Compose app with header and footer."""
        yield Header()
        yield Footer()

    def action_pop_screen(self) -> None:
        """Go back to previous screen with error handling."""
        try:
            if len(self.screen_stack) > 1:
                self.pop_screen()
        except Exception as e:
            error_msg = f"Failed to navigate back: {str(e)}"
            self.push_screen(ErrorModal(error_msg, title="Navigation Error"))

    def action_auth_debugger(self) -> None:
        """Launch auth debugger screen with error handling."""
        try:
            self.push_screen("auth_debugger")
        except Exception as e:
            error_msg = f"Failed to open auth debugger: {str(e)}\n\n{traceback.format_exc()}"
            self.push_screen(ErrorModal(error_msg, title="Screen Error"))

    def handle_exception(self, exc: Exception) -> None:
        """
        Global exception handler for the TUI app.

        This prevents the TUI from crashing and shows an error modal instead.
        """
        error_msg = f"An unexpected error occurred:\n{str(exc)}\n\n{traceback.format_exc()}"
        try:
            self.push_screen(ErrorModal(error_msg, title="Unexpected Error"))
        except Exception:
            # If we can't even show the error modal, log it and exit gracefully
            self.log.error(f"Fatal error: {error_msg}")
            self.exit(return_code=1)


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
    # Create app and push to chat screen immediately
    class ChatApp(TestMCPyApp):
        def on_mount(self) -> None:
            """Override to go directly to chat screen."""
            try:
                if self.profile:
                    self.sub_title = f"Profile: {self.profile}"
                self.push_screen("chat")
            except Exception as e:
                error_msg = f"Failed to launch chat: {str(e)}\n\n{traceback.format_exc()}"
                self.push_screen(ErrorModal(error_msg, title="Chat Launch Error"))

    app = ChatApp(profile=profile)
    app.run()
