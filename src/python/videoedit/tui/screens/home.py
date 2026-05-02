"""
Home screen - Main menu for the TUI.

Provides navigation to all main features.
"""
from textual.screen import Screen
from textual.widgets import Button, Static
from textual.containers import Vertical, Center, Horizontal


class HomeScreen(Screen):
    """Main home screen with navigation buttons."""

    def compose(self):
        """Compose the home screen."""
        with Vertical():
            yield Static("VIDEO EDIT PIPELINE SYSTEM", classes="title")
            yield Static("Build and run video editing pipelines", classes="subtitle")
            with Center():
                with Vertical(id="menu"):
                    yield Button("Browse Presets", id="btn_presets", variant="primary")
                    yield Button("Build Pipeline", id="btn_builder", variant="primary")
                    yield Button("Run Pipeline", id="btn_runner", variant="success")
                    yield Button("List Operations", id="btn_operations")
                    yield Button("Quit", id="btn_quit", variant="error")

    CSS = """
    Screen {
        align: center middle;
    }

    .title {
        text-align: center;
        text-style: bold;
        margin: 2 0;
        text-size: 150%;
        color: $primary;
    }

    .subtitle {
        text-align: center;
        margin: 0 0 3 0;
        color: $text-muted;
        text-size: 90%;
    }

    #menu {
        width: 40;
    }

    Button {
        width: 100%;
        margin: 1 0;
    }
    """

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        button_id = event.button.id

        if button_id == "btn_presets":
            from .browser import PresetBrowserScreen
            self.app.push_screen(PresetBrowserScreen())

        elif button_id == "btn_builder":
            from .builder import PipelineBuilderScreen
            self.app.push_screen(PipelineBuilderScreen())

        elif button_id == "btn_runner":
            from .runner import PipelineRunnerScreen
            self.app.push_screen(PipelineRunnerScreen())

        elif button_id == "btn_operations":
            from .operations_list import OperationsListScreen
            self.app.push_screen(OperationsListScreen())

        elif button_id == "btn_quit":
            self.app.exit()
