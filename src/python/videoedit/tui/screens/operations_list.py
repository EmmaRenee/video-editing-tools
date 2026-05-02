"""
Operations list screen - Display all available operations.

Shows information about all available pipeline operations.
"""
from textual.screen import Screen
from textual.widgets import Header, Footer, ListView, ListItem, Label, Button
from textual.containers import Vertical
from textual import on

from videoedit.operations import (
    BaseOperation,
    DetectHighlightsAudio,
    ExtractSegments,
    FormatVideo,
    TranscribeWhisper,
    BurnCaptions,
    DetectHighlightsTranscript,
    GenerateEdl,
    ConcatenateVideos,
    AddCrossfades,
    SimpleCrossfade,
    NormalizeAudio,
)


# All available operations
ALL_OPERATIONS = [
    {
        "class": TranscribeWhisper,
        "name": "Transcribe (Whisper)",
        "description": "Transcribe video with Whisper AI",
        "inputs": "video",
        "outputs": "srt, vtt, json"
    },
    {
        "class": DetectHighlightsAudio,
        "name": "Detect Highlights (Audio)",
        "description": "Find highlights via audio spike detection",
        "inputs": "video",
        "outputs": "segments"
    },
    {
        "class": DetectHighlightsTranscript,
        "name": "Detect Highlights (Transcript)",
        "description": "Find highlights via transcript analysis",
        "inputs": "transcript",
        "outputs": "segments"
    },
    {
        "class": ExtractSegments,
        "name": "Extract Segments",
        "description": "Extract clips from timestamps",
        "inputs": "video, segments",
        "outputs": "video clips"
    },
    {
        "class": FormatVideo,
        "name": "Format Video",
        "description": "Resize, crop, or pad video",
        "inputs": "video",
        "outputs": "video"
    },
    {
        "class": BurnCaptions,
        "name": "Burn Captions",
        "description": "Burn subtitles into video",
        "inputs": "video, srt",
        "outputs": "video"
    },
    {
        "class": GenerateEdl,
        "name": "Generate EDL",
        "description": "Create EDL for DaVinci Resolve",
        "inputs": "segments",
        "outputs": "edl"
    },
    {
        "class": ConcatenateVideos,
        "name": "Concatenate Videos",
        "description": "Combine multiple video clips",
        "inputs": "video clips",
        "outputs": "video"
    },
    {
        "class": AddCrossfades,
        "name": "Add Crossfades",
        "description": "Add crossfade transitions between clips",
        "inputs": "video clips",
        "outputs": "video"
    },
    {
        "class": NormalizeAudio,
        "name": "Normalize Audio",
        "description": "Normalize audio to target loudness",
        "inputs": "video",
        "outputs": "video"
    },
]


class OperationsListScreen(Screen):
    """Screen for listing all available operations."""

    def compose(self):
        """Compose the operations list screen."""
        yield Header()
        with Vertical(id="main"):
            yield Label("AVAILABLE OPERATIONS", classes="header")
            yield ListView(id="ops_lv")
            with Vertical(id="details"):
                yield Label("DETAILS", classes="header")
                yield Label("", id="op_name")
                yield Label("", id="op_desc")
                yield Label("", id="op_io")
                yield Label("", id="op_params")
            yield Button("Back", id="btn_back")
        yield Footer()

    CSS = """
    Screen {
        align: center middle;
    }

    .header {
        text-style: bold;
        color: $primary;
        text-size: 150%;
        margin: 0 0 1 0;
        text-align: center;
    }

    #main {
        width: 80;
        height: 25;
        border: solid $primary;
    }

    #ops_lv {
        height: 10;
    }

    #details {
        height: 10;
        padding: 1;
    }

    #btn_back {
        margin: 1 0 0 0;
    }
    """

    def on_mount(self) -> None:
        """Populate the operations list."""
        list_view = self.query_one("#ops_lv", ListView)
        for i, op_info in enumerate(ALL_OPERATIONS):
            yield ListItem(
                Label(f"[bold]{op_info['name']}[/bold]"),
                id=f"op_{i}"
            )
        list_view.focus()

    @on(ListView.Selected, "#ops_lv")
    def on_operation_selected(self, event: ListView.Selected) -> None:
        """Handle operation selection."""
        if event.item is None:
            return

        idx = int(event.item.id.replace("op_", ""))
        op_info = ALL_OPERATIONS[idx]

        # Update details
        self.query_one("#op_name", Label).update(
            f"[bold]Name:[/bold] {op_info['name']}"
        )
        self.query_one("#op_desc", Label).update(
            f"[bold]Description:[/bold] {op_info['description']}"
        )
        self.query_one("#op_io", Label).update(
            f"[bold]Inputs:[/bold] {op_info['inputs']}\n"
            f"[bold]Outputs:[/bold] {op_info['outputs']}"
        )

        # Get parameters from the operation class
        op_class = op_info["class"]
        if hasattr(op_class, "__init__"):
            import inspect
            sig = inspect.signature(op_class.__init__)
            params = []
            for name, param in list(sig.parameters.items())[1:]:  # Skip 'self'
                if name != "kwargs":
                    default = param.default if param.default != inspect.Parameter.empty else "required"
                    params.append(f"  {name}: {default}")

            if params:
                self.query_one("#op_params", Label).update(
                    "[bold]Parameters:[/bold]\n" + "\n".join(params)
                )
            else:
                self.query_one("#op_params", Label).update("[bold]Parameters:[/bold] None")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "btn_back":
            self.app.pop_screen()
