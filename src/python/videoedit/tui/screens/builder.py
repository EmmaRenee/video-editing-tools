"""
Pipeline builder screen - Build custom pipelines.

Provides an interface for adding, removing, and configuring
pipeline steps.
"""
from textual.screen import Screen
from textual.widgets import (
    Header, Footer, ListView, ListItem, Label,
    Button, Input, TextArea
)
from textual.containers import Horizontal, Vertical
from textual import on
from textual import events

from videoedit import Pipeline


# Available operations with their parameters
OPERATIONS = {
    "transcribe_whisper": {
        "name": "Transcribe (Whisper)",
        "description": "Transcribe video with Whisper AI",
        "params": {
            "model": {"type": "select", "options": ["tiny", "base", "small", "medium", "large"], "default": "small"}
        }
    },
    "detect_highlights_audio": {
        "name": "Detect Highlights (Audio)",
        "description": "Find highlights via audio spike detection",
        "params": {
            "threshold": {"type": "number", "default": -25},
            "max_clips": {"type": "number", "default": 10}
        }
    },
    "detect_highlights_transcript": {
        "name": "Detect Highlights (Transcript)",
        "description": "Find highlights via transcript analysis",
        "params": {
            "keywords": {"type": "text", "default": "wow,amazing,incredible"},
            "max_clips": {"type": "number", "default": 10}
        }
    },
    "extract_segments": {
        "name": "Extract Segments",
        "description": "Extract clips from timestamps",
        "params": {
            "padding": {"type": "number", "default": 0.5}
        }
    },
    "format_video": {
        "name": "Format Video",
        "description": "Resize, crop, or pad video",
        "params": {
            "aspect_ratio": {"type": "select", "options": ["9:16", "16:9", "1:1"], "default": "16:9"},
            "resolution": {"type": "select", "options": ["1080p", "720p", "480p"], "default": "1080p"}
        }
    },
    "burn_captions": {
        "name": "Burn Captions",
        "description": "Burn subtitles into video",
        "params": {
            "style": {"type": "select", "options": ["automotive_racing", "clean_tech", "social_mobile", "vin_wiki", "minimal"], "default": "automotive_racing"}
        }
    },
    "generate_edl": {
        "name": "Generate EDL",
        "description": "Create EDL for DaVinci Resolve",
        "params": {
            "fps": {"type": "select", "options": [24, 25, 30, 60], "default": 30}
        }
    },
    "concatenate_videos": {
        "name": "Concatenate Videos",
        "description": "Combine multiple video clips",
        "params": {
            "reencode": {"type": "boolean", "default": False}
        }
    },
    "add_crossfades": {
        "name": "Add Crossfades",
        "description": "Add crossfade transitions between clips",
        "params": {
            "duration": {"type": "number", "default": 0.5},
            "transition": {"type": "select", "options": ["fade", "dissolve", "wipeleft", "wiperight"], "default": "fade"}
        }
    },
    "normalize_audio": {
        "name": "Normalize Audio",
        "description": "Normalize audio to target loudness",
        "params": {
            "preset": {"type": "select", "options": ["ebu", "atsc", "podcast", "youtube", "spotify"], "default": "ebu"}
        }
    },
}


class PipelineBuilderScreen(Screen):
    """Screen for building custom pipelines."""

    def __init__(self, preset: str | None = None):
        """Initialize the builder screen."""
        super().__init__()
        self.preset = preset
        self.pipeline = Pipeline()
        self._load_preset_if_needed()

    def _load_preset_if_needed(self):
        """Load preset if provided."""
        if self.preset:
            from ..presets import PRESETS
            if self.preset in PRESETS:
                preset_data = PRESETS[self.preset]
                self.pipeline.name = preset_data["name"]
                self.pipeline.description = preset_data["description"]
                for step_data in preset_data["steps"]:
                    self.pipeline.add(
                        step_data["operation"],
                        name=step_data.get("name"),
                        input_from=step_data.get("input"),
                        **step_data.get("params", {})
                    )

    def compose(self):
        """Compose the builder screen."""
        yield Header()
        with Horizontal():
            # Left: Available operations
            with Vertical(id="available_ops"):
                yield Label("AVAILABLE OPERATIONS", classes="header")
                yield ListView(id="ops_lv")

            # Middle: Pipeline steps
            with Vertical(id="pipeline_steps"):
                yield Label("PIPELINE STEPS", classes="header")
                yield ListView(id="steps_lv")
                with Horizontal(id="step_actions"):
                    yield Button("Add", id="btn_add", variant="success")
                    yield Button("Remove", id="btn_remove")
                    yield Button("Edit", id="btn_edit", variant="primary")
                    yield Button("Move Up", id="btn_up")
                    yield Button("Move Down", id="btn_down")

            # Right: Step details
            with Vertical(id="step_details"):
                yield Label("STEP DETAILS", classes="header")
                yield Label("Select a step to view/edit details", id="step_info")
                yield Label("", id="step_params")
        with Horizontal(id="bottom_actions"):
            yield Button("Save Pipeline", id="btn_save", variant="primary")
            yield Button("Load Pipeline", id="btn_load")
            yield Button("Run Pipeline", id="btn_run", variant="success")
            yield Button("Back", id="btn_back")
        yield Footer()

    CSS = """
    Screen {
        layout: vertical;
    }

    #available_ops {
        width: 30%;
        height: 1fr;
        border: solid $primary;
    }

    #pipeline_steps {
        width: 35%;
        height: 1fr;
        border: solid $primary;
    }

    #step_details {
        width: 35%;
        height: 1fr;
        padding: 1;
    }

    .header {
        text-style: bold;
        color: $primary;
        margin: 0 0 1 0;
    }

    #step_actions {
        margin: 1 0;
    }

    #step_actions Button {
        margin: 0 1 0 0;
    }

    #bottom_actions {
        margin: 1 0 0 0;
    }

    #bottom_actions Button {
        margin: 0 1 0 0;
    }
    """

    def on_mount(self) -> None:
        """Populate the operations list."""
        list_view = self.query_one("#ops_lv", ListView)
        for op_key, op_info in OPERATIONS.items():
            yield ListItem(
                Label(f"[bold]{op_info['name']}[/bold]\n{op_info['description'][:40]}..."),
                id=f"op_{op_key}"
            )

        self._refresh_steps_list()

    def _refresh_steps_list(self):
        """Refresh the pipeline steps list."""
        steps_lv = self.query_one("#steps_lv", ListView)
        steps_lv.clear()

        for i, step in enumerate(self.pipeline.steps):
            yield ListItem(
                Label(f"{i+1}. {step.name}\n    Operation: {step.operation}"),
                id=f"step_{i}"
            )

    @on(ListView.Selected, "#ops_lv")
    def on_operation_selected(self, event: ListView.Selected) -> None:
        """Handle operation selection."""
        pass  # Selection shows details, Add button adds to pipeline

    @on(ListView.Selected, "#steps_lv")
    def on_step_selected(self, event: ListView.Selected) -> None:
        """Handle step selection."""
        if event.item is None:
            return

        step_idx = int(event.item.id.replace("step_", ""))
        step = self.pipeline.steps[step_idx]

        # Show step info
        self.query_one("#step_info", Label).update(
            f"[bold]Name:[/bold] {step.name}\n"
            f"[bold]Operation:[/bold] {step.operation}\n"
            f"[bold]Input from:[/bold] {step.input_from or 'None'}"
        )

        # Show params
        if step.params:
            params_text = "[bold]Parameters:[/bold]\n"
            for key, value in step.params.items():
                params_text += f"  {key}: {value}\n"
            self.query_one("#step_params", Label).update(params_text)
        else:
            self.query_one("#step_params", Label).update("[bold]Parameters:[/bold] None")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        button_id = event.button.id

        if button_id == "btn_back":
            self.app.pop_screen()

        elif button_id == "btn_add":
            ops_lv = self.query_one("#ops_lv", ListView)
            if ops_lv.highlighted_child:
                op_key = ops_lv.highlighted_child.id.replace("op_", "")
                self.pipeline.add(op_key)
                self._refresh_steps_list()

        elif button_id == "btn_remove":
            steps_lv = self.query_one("#steps_lv", ListView)
            if steps_lv.highlighted_child:
                step_idx = int(steps_lv.highlighted_child.id.replace("step_", ""))
                self.pipeline.remove(self.pipeline.steps[step_idx].name)
                self._refresh_steps_list()

        elif button_id == "btn_edit":
            steps_lv = self.query_one("#steps_lv", ListView)
            if steps_lv.highlighted_child:
                step_idx = int(steps_lv.highlighted_child.id.replace("step_", ""))
                step = self.pipeline.steps[step_idx]
                operation_info = OPERATIONS.get(step.operation, {})

                def on_editor_closed(result):
                    if result and result.get("action") == "save":
                        self._refresh_steps_list()

                from ..widgets.step_editor import StepEditorScreen
                self.push_screen(
                    StepEditorScreen(step, step.operation, step_idx, operation_info),
                    callback=on_editor_closed
                )

        elif button_id == "btn_up":
            steps_lv = self.query_one("#steps_lv", ListView)
            if steps_lv.highlighted_child:
                step_idx = int(steps_lv.highlighted_child.id.replace("step_", ""))
                if step_idx > 0:
                    step = self.pipeline.steps.pop(step_idx)
                    self.pipeline.steps.insert(step_idx - 1, step)
                    self._refresh_steps_list()

        elif button_id == "btn_down":
            steps_lv = self.query_one("#steps_lv", ListView)
            if steps_lv.highlighted_child:
                step_idx = int(steps_lv.highlighted_child.id.replace("step_", ""))
                if step_idx < len(self.pipeline.steps) - 1:
                    step = self.pipeline.steps.pop(step_idx)
                    self.pipeline.steps.insert(step_idx + 1, step)
                    self._refresh_steps_list()

        elif button_id == "btn_save":
            self.app.save_pipeline(self.pipeline)

        elif button_id == "btn_load":
            self.app.load_pipeline()

        elif button_id == "btn_run":
            from .runner import PipelineRunnerScreen
            self.app.push_screen(PipelineRunnerScreen(pipeline=self.pipeline))
