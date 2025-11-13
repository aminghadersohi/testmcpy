"""
Auth Flow Widget for displaying authentication flow steps.

Shows step-by-step progress of OAuth/JWT/Bearer authentication flows
with timing, status indicators, and expandable details.
"""

from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widget import Widget
from textual.widgets import Static, Collapsible


class AuthFlowStep(Widget):
    """Individual auth flow step with status and details."""

    DEFAULT_CSS = """
    AuthFlowStep {
        height: auto;
        padding: 0 1;
    }

    AuthFlowStep .step-header {
        color: $text;
    }

    AuthFlowStep .step-success {
        color: $success;
    }

    AuthFlowStep .step-error {
        color: $error;
    }

    AuthFlowStep .step-pending {
        color: $text-muted;
    }

    AuthFlowStep .step-details {
        color: $text-muted;
        padding-left: 4;
    }
    """

    def __init__(
        self,
        step_number: int,
        step_name: str,
        status: str = "pending",  # pending, success, error
        duration_ms: float | None = None,
        details: dict[str, Any] | None = None,
        *args,
        **kwargs,
    ):
        """
        Initialize an auth flow step.

        Args:
            step_number: Step number in the flow
            step_name: Name/description of the step
            status: Step status (pending, success, error)
            duration_ms: Duration in milliseconds
            details: Additional details to show
        """
        super().__init__(*args, **kwargs)
        self.step_number = step_number
        self.step_name = step_name
        self.status = status
        self.duration_ms = duration_ms
        self.details = details or {}

    def compose(self) -> ComposeResult:
        """Compose the step widget."""
        # Step header with status
        header_text = Text()

        # Status icon
        if self.status == "success":
            header_text.append("✓ ", style="green bold")
        elif self.status == "error":
            header_text.append("✗ ", style="red bold")
        else:
            header_text.append("○ ", style="dim")

        # Step number and name
        header_text.append(f"{self.step_number}. ", style="dim")
        header_text.append(self.step_name, style="bold" if self.status == "success" else "")

        # Duration if available
        if self.duration_ms is not None:
            header_text.append(f" ({self.duration_ms:.0f}ms)", style="dim")

        yield Static(header_text, classes="step-header")

        # Expandable details if available
        if self.details:
            with Collapsible(title="Details", collapsed=True):
                details_text = Text()
                for key, value in self.details.items():
                    details_text.append(f"{key}: ", style="dim")
                    details_text.append(str(value), style="cyan")
                    details_text.append("\n")
                yield Static(details_text, classes="step-details")

    def update_status(
        self,
        status: str,
        duration_ms: float | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Update the step status and details."""
        self.status = status
        if duration_ms is not None:
            self.duration_ms = duration_ms
        if details is not None:
            self.details = details
        self.refresh(recompose=True)


class AuthFlowWidget(Widget):
    """Widget to display authentication flow steps with status."""

    DEFAULT_CSS = """
    AuthFlowWidget {
        height: auto;
        background: $panel;
        border: solid $primary;
        padding: 1;
        margin: 1;
    }

    AuthFlowWidget #flow-title {
        color: $accent;
        text-style: bold;
        padding-bottom: 1;
    }

    AuthFlowWidget #flow-summary {
        color: $text-muted;
        padding-top: 1;
        border-top: solid $border;
    }

    AuthFlowWidget #steps-container {
        height: auto;
    }
    """

    def __init__(
        self,
        flow_type: str = "OAuth",
        steps: list[dict[str, Any]] | None = None,
        *args,
        **kwargs,
    ):
        """
        Initialize auth flow widget.

        Args:
            flow_type: Type of auth flow (OAuth, JWT, Bearer)
            steps: List of step dictionaries with keys: step, success, timestamp, data
        """
        super().__init__(*args, **kwargs)
        self.flow_type = flow_type
        self.steps_data = steps or []
        self.step_widgets: list[AuthFlowStep] = []

    def compose(self) -> ComposeResult:
        """Compose the auth flow widget."""
        # Title
        title_text = Text()
        title_text.append(f"{self.flow_type} Flow Steps", style="bold cyan")
        yield Static(title_text, id="flow-title")

        # Steps container
        with Vertical(id="steps-container"):
            if not self.steps_data:
                no_steps_text = Text()
                no_steps_text.append("No authentication flow steps to display", style="dim")
                yield Static(no_steps_text)
            else:
                for i, step_data in enumerate(self.steps_data, 1):
                    step_widget = AuthFlowStep(
                        step_number=i,
                        step_name=step_data.get("step", "Unknown Step"),
                        status="success" if step_data.get("success", False) else "error",
                        duration_ms=step_data.get("timestamp", 0) * 1000,
                        details=step_data.get("data", {}),
                    )
                    self.step_widgets.append(step_widget)
                    yield step_widget

        # Summary
        if self.steps_data:
            total_time = max((s.get("timestamp", 0) for s in self.steps_data), default=0)
            success_count = sum(1 for s in self.steps_data if s.get("success", False))
            total_count = len(self.steps_data)

            summary_text = Text()
            summary_text.append(f"\nDuration: {total_time * 1000:.0f}ms", style="dim")
            summary_text.append(" │ ", style="dim")
            summary_text.append(f"Steps: {success_count}/{total_count} passed",
                              style="green" if success_count == total_count else "yellow")

            yield Static(summary_text, id="flow-summary")

    def update_flow(self, steps: list[dict[str, Any]]) -> None:
        """Update the flow with new steps."""
        self.steps_data = steps
        self.step_widgets = []
        self.refresh(recompose=True)

    def add_step(self, step_data: dict[str, Any]) -> None:
        """Add a new step to the flow."""
        self.steps_data.append(step_data)
        self.refresh(recompose=True)
