"""
Auth Debugger Screen for interactive authentication debugging.

Provides a multi-panel interface for debugging OAuth, JWT, and Bearer token
authentication flows with detailed request/response inspection and token analysis.
"""

import json
from typing import Any

from rich.syntax import Syntax
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Input, Label, Select, Static

from testmcpy.auth_debugger import AuthDebugger
from testmcpy.tui.widgets.auth_flow_widget import AuthFlowWidget
from testmcpy.tui.widgets.header import Header


class AuthConfigPanel(Container):
    """Left panel for auth configuration."""

    DEFAULT_CSS = """
    AuthConfigPanel {
        width: 1fr;
        height: 100%;
        border: solid $primary;
        background: $panel;
        padding: 1;
    }

    AuthConfigPanel .panel-title {
        color: $accent;
        text-style: bold;
        padding-bottom: 1;
    }

    AuthConfigPanel .config-field {
        height: auto;
        margin: 1 0;
    }

    AuthConfigPanel .field-label {
        color: $text-muted;
        width: 20;
    }

    AuthConfigPanel .field-value {
        color: $text;
    }

    AuthConfigPanel Button {
        margin: 1 0;
    }
    """

    def __init__(self, *args, **kwargs):
        """Initialize auth config panel."""
        super().__init__(*args, **kwargs)
        self.auth_type = "oauth"
        self.config_data: dict[str, Any] = {}

    def compose(self) -> ComposeResult:
        """Compose the config panel."""
        # Title
        yield Static("Configuration", classes="panel-title")

        # Auth type selector
        with Horizontal(classes="config-field"):
            yield Label("Auth Type", classes="field-label")
            yield Select(
                [
                    ("OAuth 2.0", "oauth"),
                    ("JWT Dynamic", "jwt"),
                    ("Bearer Token", "bearer"),
                ],
                value="oauth",
                id="auth-type-select",
            )

        # Config fields (will be dynamic based on auth type)
        yield Container(id="config-fields")

        # Action buttons
        yield Button("Edit Config [e]", id="edit-config", variant="primary")
        yield Button("Retry Auth [r]", id="retry-auth", variant="success")

    def update_config_fields(self, auth_type: str) -> None:
        """Update config fields based on auth type."""
        self.auth_type = auth_type
        # This would be implemented to show different fields based on auth type
        # For now, we'll keep it simple
        self.refresh()


class FlowStepsPanel(Container):
    """Middle panel for flow steps visualization."""

    DEFAULT_CSS = """
    FlowStepsPanel {
        width: 1fr;
        height: 100%;
        border: solid $primary;
        background: $panel;
        padding: 1;
    }

    FlowStepsPanel .panel-title {
        color: $accent;
        text-style: bold;
        padding-bottom: 1;
    }
    """

    def __init__(self, *args, **kwargs):
        """Initialize flow steps panel."""
        super().__init__(*args, **kwargs)
        self.flow_widget: AuthFlowWidget | None = None

    def compose(self) -> ComposeResult:
        """Compose the flow steps panel."""
        yield Static("Flow Steps", classes="panel-title")

        # Auth flow widget
        self.flow_widget = AuthFlowWidget(flow_type="OAuth")
        yield self.flow_widget

    def update_steps(self, steps: list[dict[str, Any]], flow_type: str = "OAuth") -> None:
        """Update the flow steps."""
        if self.flow_widget:
            self.flow_widget.flow_type = flow_type
            self.flow_widget.update_flow(steps)


class RequestResponsePanel(VerticalScroll):
    """Right panel for request/response details."""

    DEFAULT_CSS = """
    RequestResponsePanel {
        width: 1fr;
        height: 100%;
        border: solid $primary;
        background: $panel;
        padding: 1;
    }

    RequestResponsePanel .panel-title {
        color: $accent;
        text-style: bold;
        padding-bottom: 1;
    }

    RequestResponsePanel .section-title {
        color: $secondary;
        text-style: bold;
        padding: 1 0;
    }

    RequestResponsePanel .code-block {
        background: $surface;
        padding: 1;
        margin: 1 0;
        border: solid $border;
    }
    """

    def __init__(self, *args, **kwargs):
        """Initialize request/response panel."""
        super().__init__(*args, **kwargs)
        self.request_data: dict[str, Any] = {}
        self.response_data: dict[str, Any] = {}

    def compose(self) -> ComposeResult:
        """Compose the request/response panel."""
        yield Static("Request & Response Details", classes="panel-title")

        # Request section
        yield Static("Request", classes="section-title")
        yield Container(id="request-details", classes="code-block")

        # Response section
        yield Static("Response", classes="section-title")
        yield Container(id="response-details", classes="code-block")

    def update_request(self, request_data: dict[str, Any]) -> None:
        """Update the request details."""
        self.request_data = request_data
        request_container = self.query_one("#request-details", Container)
        request_container.remove_children()

        if request_data:
            request_text = Text()
            if "url" in request_data:
                request_text.append(f"POST {request_data['url']}\n\n", style="bold")

            if "headers" in request_data:
                request_text.append("Headers:\n", style="cyan")
                for key, value in request_data["headers"].items():
                    request_text.append(f"  {key}: {value}\n", style="dim")
                request_text.append("\n")

            if "body" in request_data:
                request_text.append("Body:\n", style="cyan")
                request_text.append(json.dumps(request_data["body"], indent=2), style="dim")

            request_container.mount(Static(request_text))

    def update_response(self, response_data: dict[str, Any]) -> None:
        """Update the response details."""
        self.response_data = response_data
        response_container = self.query_one("#response-details", Container)
        response_container.remove_children()

        if response_data:
            response_text = Text()
            if "status_code" in response_data:
                status_style = "green" if response_data["status_code"] < 400 else "red"
                response_text.append(f"Status: {response_data['status_code']}\n\n", style=f"bold {status_style}")

            if "headers" in response_data:
                response_text.append("Headers:\n", style="cyan")
                for key, value in response_data["headers"].items():
                    response_text.append(f"  {key}: {value}\n", style="dim")
                response_text.append("\n")

            if "body" in response_data:
                response_text.append("Body:\n", style="cyan")
                try:
                    body_json = json.loads(response_data["body"]) if isinstance(response_data["body"], str) else response_data["body"]
                    response_text.append(json.dumps(body_json, indent=2), style="dim")
                except:
                    response_text.append(str(response_data["body"]), style="dim")

            response_container.mount(Static(response_text))


class TokenDetailsPanel(VerticalScroll):
    """Bottom panel for token details and JWT claims."""

    DEFAULT_CSS = """
    TokenDetailsPanel {
        height: auto;
        max-height: 20;
        border: solid $primary;
        background: $panel;
        padding: 1;
    }

    TokenDetailsPanel .panel-title {
        color: $accent;
        text-style: bold;
        padding-bottom: 1;
    }

    TokenDetailsPanel .token-field {
        padding: 0 1;
        color: $text-muted;
    }

    TokenDetailsPanel .actions {
        padding-top: 1;
    }

    TokenDetailsPanel Button {
        margin: 0 1 0 0;
    }
    """

    def __init__(self, *args, **kwargs):
        """Initialize token details panel."""
        super().__init__(*args, **kwargs)
        self.token: str | None = None
        self.token_data: dict[str, Any] = {}

    def compose(self) -> ComposeResult:
        """Compose the token details panel."""
        yield Static("Token Details", classes="panel-title")

        # Token info
        yield Container(id="token-info")

        # Actions
        with Horizontal(classes="actions"):
            yield Button("Verify Token [v]", id="verify-token", variant="primary")
            yield Button("Copy Token [c]", id="copy-token")
            yield Button("Test with MCP [t]", id="test-mcp", variant="success")

    def update_token(self, token: str, token_data: dict[str, Any]) -> None:
        """Update the token details."""
        self.token = token
        self.token_data = token_data

        token_container = self.query_one("#token-info", Container)
        token_container.remove_children()

        # Display token info
        token_text = Text()
        if "token_type" in token_data:
            token_text.append(f"Type: {token_data['token_type']}\n", style="dim")
        if "token_length" in token_data:
            token_text.append(f"Length: {token_data['token_length']} characters\n", style="dim")
        if "expires_in" in token_data:
            token_text.append(f"Expires: {token_data['expires_in']}s\n", style="dim")

        # Try to decode JWT claims
        if token and token.count('.') == 2:  # JWT format
            try:
                import base64
                # Decode JWT payload (middle part)
                parts = token.split('.')
                # Add padding if needed
                payload = parts[1]
                payload += '=' * (4 - len(payload) % 4)
                decoded = base64.urlsafe_b64decode(payload)
                claims = json.loads(decoded)

                token_text.append("\nJWT Claims:\n", style="cyan bold")
                for key, value in claims.items():
                    token_text.append(f"  {key}: ", style="dim")
                    token_text.append(f"{value}\n", style="cyan")
            except Exception as e:
                token_text.append(f"\nCould not decode JWT: {e}\n", style="yellow")

        token_container.mount(Static(token_text, classes="token-field"))


class AuthDebuggerScreen(Screen):
    """Interactive auth debugger screen."""

    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back", show=True),
        Binding("e", "edit_config", "Edit Config", show=False),
        Binding("r", "retry_auth", "Retry", show=False),
        Binding("v", "verify_token", "Verify Token", show=False),
        Binding("c", "copy_token", "Copy Token", show=False),
        Binding("t", "test_mcp", "Test MCP", show=False),
        Binding("h", "app.push_screen('home')", "Home", show=True),
        Binding("?", "help", "Help", show=True),
    ]

    DEFAULT_CSS = """
    AuthDebuggerScreen {
        background: $surface;
    }

    #main-container {
        height: 100%;
        width: 100%;
    }

    #top-panels {
        height: 3fr;
    }

    #bottom-panel {
        height: 1fr;
    }
    """

    def __init__(self, profile: str | None = None, *args, **kwargs):
        """
        Initialize auth debugger screen.

        Args:
            profile: MCP profile to use for auth debugging
        """
        super().__init__(*args, **kwargs)
        self.profile = profile
        self.debugger = AuthDebugger(enabled=False)
        self.config_panel: AuthConfigPanel | None = None
        self.flow_panel: FlowStepsPanel | None = None
        self.request_response_panel: RequestResponsePanel | None = None
        self.token_panel: TokenDetailsPanel | None = None

    def compose(self) -> ComposeResult:
        """Compose the auth debugger screen."""
        # Header
        yield Header(profile=self.profile, connected=False)

        # Main container
        with VerticalScroll(id="main-container"):
            # Top panels (3 columns)
            with Horizontal(id="top-panels"):
                self.config_panel = AuthConfigPanel()
                yield self.config_panel

                self.flow_panel = FlowStepsPanel()
                yield self.flow_panel

                self.request_response_panel = RequestResponsePanel()
                yield self.request_response_panel

            # Bottom panel (token details)
            self.token_panel = TokenDetailsPanel()
            yield self.token_panel

    def on_mount(self) -> None:
        """Handle screen mount."""
        # Load sample data for demonstration
        self._load_sample_auth_flow()

    def _load_sample_auth_flow(self) -> None:
        """Load sample auth flow for demonstration."""
        # Sample OAuth flow
        sample_steps = [
            {
                "step": "OAuth Request Prepared",
                "success": True,
                "timestamp": 0.001,
                "data": {
                    "grant_type": "client_credentials",
                    "client_id": "sample-client-123",
                    "scope": "read write"
                }
            },
            {
                "step": "Sending POST to Token Endpoint",
                "success": True,
                "timestamp": 0.002,
                "data": {
                    "url": "https://auth.example.com/oauth/token",
                    "headers": {"Content-Type": "application/x-www-form-urlencoded"}
                }
            },
            {
                "step": "Response Received",
                "success": True,
                "timestamp": 0.234,
                "data": {
                    "status_code": 200,
                    "headers": {
                        "content-type": "application/json",
                        "cache-control": "no-store"
                    }
                }
            },
            {
                "step": "Token Extracted",
                "success": True,
                "timestamp": 0.235,
                "data": {
                    "token_length": 1243,
                    "token_preview": "eyJhbGciOiJSUzI1NiIs...",
                    "expires_in": 3600,
                    "scope": "read write"
                }
            }
        ]

        if self.flow_panel:
            self.flow_panel.update_steps(sample_steps, "OAuth")

        # Sample request
        sample_request = {
            "url": "https://auth.example.com/oauth/token",
            "headers": {
                "Content-Type": "application/x-www-form-urlencoded"
            },
            "body": {
                "grant_type": "client_credentials",
                "client_id": "sample-client-123",
                "client_secret": "***",
                "scope": "read write"
            }
        }

        if self.request_response_panel:
            self.request_response_panel.update_request(sample_request)

        # Sample response
        sample_response = {
            "status_code": 200,
            "headers": {
                "content-type": "application/json",
                "cache-control": "no-store"
            },
            "body": {
                "access_token": "eyJhbGciOiJSUzI1NiIs...",
                "token_type": "Bearer",
                "expires_in": 3600,
                "scope": "read write"
            }
        }

        if self.request_response_panel:
            self.request_response_panel.update_response(sample_response)

        # Sample token
        sample_token = "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJhdXRoLmV4YW1wbGUuY29tIiwic3ViIjoic2FtcGxlLWNsaWVudC0xMjMiLCJhdWQiOiJhcGkuZXhhbXBsZS5jb20iLCJleHAiOjE3MzEzNDEwMjUsImlhdCI6MTczMTMzNzQyNSwic2NvcGUiOiJyZWFkIHdyaXRlIn0.signature"
        sample_token_data = {
            "token_type": "Bearer",
            "token_length": len(sample_token),
            "expires_in": 3600
        }

        if self.token_panel:
            self.token_panel.update_token(sample_token, sample_token_data)

    def action_edit_config(self) -> None:
        """Handle edit config action."""
        self.notify("Edit config - Not implemented yet", severity="information")

    def action_retry_auth(self) -> None:
        """Handle retry auth action."""
        self.notify("Retrying authentication...", severity="information")
        # This would trigger actual auth flow

    def action_verify_token(self) -> None:
        """Handle verify token action."""
        if self.token_panel and self.token_panel.token:
            self.notify("Token verification - Not implemented yet", severity="information")
        else:
            self.notify("No token to verify", severity="warning")

    def action_copy_token(self) -> None:
        """Handle copy token action."""
        if self.token_panel and self.token_panel.token:
            # In a real implementation, this would copy to clipboard
            self.notify("Token copied to clipboard (mock)", severity="success")
        else:
            self.notify("No token to copy", severity="warning")

    def action_test_mcp(self) -> None:
        """Handle test with MCP action."""
        if self.token_panel and self.token_panel.token:
            self.notify("Testing token with MCP - Not implemented yet", severity="information")
        else:
            self.notify("No token to test", severity="warning")

    def action_help(self) -> None:
        """Show help information."""
        help_text = """
Auth Debugger Help:

[e] Edit Config - Edit authentication configuration
[r] Retry Auth - Retry authentication flow
[v] Verify Token - Verify token validity
[c] Copy Token - Copy token to clipboard
[t] Test MCP - Test token with MCP server
[h] Home - Return to home screen
[ESC] Back - Go back to previous screen
        """
        self.notify(help_text.strip(), timeout=10)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        button_id = event.button.id

        if button_id == "edit-config":
            self.action_edit_config()
        elif button_id == "retry-auth":
            self.action_retry_auth()
        elif button_id == "verify-token":
            self.action_verify_token()
        elif button_id == "copy-token":
            self.action_copy_token()
        elif button_id == "test-mcp":
            self.action_test_mcp()

    def on_select_changed(self, event: Select.Changed) -> None:
        """Handle select changes."""
        if event.select.id == "auth-type-select":
            auth_type = str(event.value)
            if self.config_panel:
                self.config_panel.update_config_fields(auth_type)
            self.notify(f"Auth type changed to: {auth_type}", severity="information")
