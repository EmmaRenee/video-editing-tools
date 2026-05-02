"""
Preset browser screen - Browse and load preset pipelines.

Displays available presets with descriptions and allows loading
them into the builder or running directly.
"""
from textual.screen import Screen
from textual.widgets import Header, Footer, ListView, ListItem, Label, Button
from textual.containers import Horizontal, Vertical
from textual import on

from ..presets import PRESETS


class PresetBrowserScreen(Screen):
    """Screen for browsing and selecting pipeline presets."""

    def compose(self):
        """Compose the preset browser screen."""
        yield Header()
        with Horizontal():
            # Left: Preset list
            with Vertical(id="preset_list"):
                yield Label("PRESETS", classes="header")
                yield ListView(id="presets_lv")

            # Right: Details and actions
            with Vertical(id="details"):
                yield Label("DETAILS", classes="header")
                yield Label("", id="preset_name")
                yield Label("", id="preset_desc")
                yield Label("", id="preset_steps")
                with Horizontal(id="actions"):
                    yield Button("Load in Builder", id="btn_load", variant="primary")
                    yield Button("Run Now", id="btn_run", variant="success")
                yield Button("Back", id="btn_back")
        yield Footer()

    CSS = """
    Screen {
        layout: horizontal;
    }

    #preset_list {
        width: 40%;
        height: 1fr;
        border: solid $primary;
    }

    #details {
        width: 60%;
        height: 1fr;
        padding: 1;
    }

    .header {
        text-style: bold;
        color: $primary;
        margin: 0 0 1 0;
    }

    #preset_name {
        text-style: bold;
        text-size: 120%;
        margin: 0 0 1 0;
    }

    #preset_desc {
        margin: 0 0 1 0;
    }

    #preset_steps {
        margin: 0 0 2 0;
    }

    #actions {
        margin: 0 0 1 0;
    }

    Button {
        margin: 0 1 0 0;
    }
    """

    def on_mount(self) -> None:
        """Populate the preset list."""
        list_view = self.query_one("#presets_lv", ListView)
        for preset_key in PRESETS:
            preset = PRESETS[preset_key]
            yield ListItem(
                Label(f"[bold]{preset['name']}[/bold]\n{preset['description'][:50]}..."),
                id=f"preset_{preset_key}"
            )
        list_view.focus()

    @on(ListView.Selected, "#presets_lv")
    def on_preset_selected(self, event: ListView.Selected) -> None:
        """Handle preset selection."""
        if event.item is None:
            return

        preset_key = event.item.id.replace("preset_", "")
        preset = PRESETS[preset_key]

        # Update details
        self.query_one("#preset_name", Label).update(f"[bold]{preset['name']}[/bold]")
        self.query_one("#preset_desc", Label).update(preset['description'])

        # Show steps
        steps_text = f"Steps: {len(preset['steps'])}\n"
        for i, step in enumerate(preset['steps'], 1):
            steps_text += f"  {i}. {step['operation']}\n"
        self.query_one("#preset_steps", Label).update(steps_text)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        button_id = event.button.id

        if button_id == "btn_back":
            self.app.pop_screen()

        elif button_id == "btn_load":
            # Get selected preset
            list_view = self.query_one("#presets_lv", ListView)
            if list_view.highlighted_child:
                preset_key = list_view.highlighted_child.id.replace("preset_", "")
                from .builder import PipelineBuilderScreen
                self.app.pop_screen()
                self.app.push_screen(PipelineBuilderScreen(preset=preset_key))

        elif button_id == "btn_run":
            # Get selected preset
            list_view = self.query_one("#presets_lv", ListView)
            if list_view.highlighted_child:
                preset_key = list_view.highlighted_child.id.replace("preset_", "")
                from .runner import PipelineRunnerScreen
                self.app.pop_screen()
                self.app.push_screen(PipelineRunnerScreen(preset=preset_key))
