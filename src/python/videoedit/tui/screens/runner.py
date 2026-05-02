"""
Pipeline runner screen - Execute pipelines with live progress.

Provides file selection and real-time progress display for
pipeline execution.
"""
from pathlib import Path
from textual.screen import Screen
from textual.widgets import Header, Footer, Label, Button, Input, ProgressBar
from textual.containers import Horizontal, Vertical
from textual import work, bind
from textual.app import ComposeResult

from videoedit import Pipeline, Runner
from videoedit.utils.progress import ProgressTracker


class PipelineRunnerScreen(Screen):
    """Screen for running pipelines."""

    def __init__(self, preset: str | None = None, pipeline: Pipeline | None = None):
        """Initialize the runner screen."""
        super().__init__()
        self.preset = preset
        self.pipeline = pipeline
        self.input_file = None
        self.output_dir = None
        self.running = False

    def compose(self) -> ComposeResult:
        """Compose the runner screen."""
        yield Header()
        with Vertical(id="main"):
            yield Label("RUN PIPELINE", classes="header")

            # Input file selection
            with Horizontal(id="input_section"):
                yield Label("Input Video:", classes="label")
                yield Input(placeholder="/path/to/video.mp4", id="input_file", value="")
                yield Button("Browse", id="btn_browse_input")

            # Output directory selection
            with Horizontal(id="output_section"):
                yield Label("Output Dir:", classes="label")
                yield Input(placeholder="/path/to/output", id="output_dir", value="")
                yield Button("Browse", id="btn_browse_output")

            # Pipeline info
            yield Label("", id="pipeline_info")

            # Progress section
            with Vertical(id="progress_section"):
                yield Label("Progress:", classes="label")
                yield ProgressBar(total=100, show_eta=True, id="progress_bar")
                yield Label("", id="progress_status")
                yield Label("", id="progress_detail")

            # Log output
            with Vertical(id="log_section"):
                yield Label("Log:", classes="label")
                yield Label("", id="log_output", scroll=True)

        with Horizontal(id="actions"):
            yield Button("Run Pipeline", id="btn_run", variant="success")
            yield Button("Stop", id="btn_stop", variant="error", disabled=True)
            yield Button("Back", id="btn_back")
        yield Footer()

    CSS = """
    Screen {
        layout: vertical;
    }

    .header {
        text-style: bold;
        color: $primary;
        text-size: 150%;
        margin: 0 0 2 0;
    }

    .label {
        margin: 1 0 0 0;
        text-style: bold;
    }

    #input_section, #output_section {
        margin: 1 0;
    }

    Label {
        width: 15%;
    }

    Input {
        width: 65%;
    }

    #progress_section {
        margin: 2 0;
    }

    #log_section {
        height: 15;
        border: solid $panel;
        padding: 1;
    }

    #log_output {
        height: 1fr;
        text-style: dim;
    }

    #actions {
        margin: 1 0 0 0;
    }

    #actions Button {
        margin: 0 1 0 0;
    }
    """

    def on_mount(self) -> None:
        """Initialize the screen."""
        # Load pipeline if preset provided
        if self.preset and not self.pipeline:
            from ..presets import PRESETS
            if self.preset in PRESETS:
                preset_data = PRESETS[self.preset]
                self.pipeline = Pipeline.from_dict(preset_data)

        # Show pipeline info
        self._update_pipeline_info()

        # Set default output directory
        self.query_one("#output_dir", Input).value = str(Path.cwd() / "output")

    def _update_pipeline_info(self):
        """Update pipeline info display."""
        if self.pipeline:
            info = f"[bold]Pipeline:[/bold] {self.pipeline.name}\n"
            info += f"[bold]Steps:[/bold] {len(self.pipeline.steps)}\n"
            for i, step in enumerate(self.pipeline.steps, 1):
                info += f"  {i}. {step.operation}\n"
            self.query_one("#pipeline_info", Label).update(info)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        button_id = event.button.id

        if button_id == "btn_back":
            if self.running:
                return  # Can't go back while running
            self.app.pop_screen()

        elif button_id == "btn_browse_input":
            self._browse_input()

        elif button_id == "btn_browse_output":
            self._browse_output()

        elif button_id == "btn_run":
            self._run_pipeline()

        elif button_id == "btn_stop":
            self.running = False
            self.query_one("#progress_status", Label).update("[bold]Stopping...[/bold]")

    def _browse_input(self):
        """Browse for input file."""
        # For now, just update the input with user typing
        # In a full implementation, would use a file browser widget
        self.query_one("#input_file", Input).focus()

    def _browse_output(self):
        """Browse for output directory."""
        self.query_one("#output_dir", Input).focus()

    @work(exclusive=True)
    async def _run_pipeline(self) -> None:
        """Run the pipeline."""
        if not self.pipeline:
            self.query_one("#log_output", Label).update("[red]No pipeline loaded[/red]")
            return

        # Get input and output
        input_file = self.query_one("#input_file", Input).value
        output_dir = self.query_one("#output_dir", Input).value

        if not input_file or not Path(input_file).exists():
            self.query_one("#log_output", Label).update("[red]Invalid input file[/red]")
            return

        self.running = True
        self.query_one("#btn_run", Button).disabled = True
        self.query_one("#btn_stop", Button).disabled = False
        self.query_one("#progress_bar", ProgressBar).update(total=100)

        # Create tracker with UI callbacks
        tracker = TUIProgressTracker(self)

        try:
            runner = Runner(self.pipeline, progress=tracker)

            self.query_one("#log_output", Label).update("[green]Starting pipeline...[/green]\n")

            # Run the pipeline
            result = runner.run(input_file, output_dir)

            if result["success"]:
                self.query_one("#progress_bar", ProgressBar).progress = 100
                self.query_one("#progress_status", Label).update("[bold green]Complete![/bold green]")
                self.query_one("#log_output", Label).update(
                    self.query_one("#log_output", Label).renderable +
                    f"\n[green]Pipeline completed successfully![/green]"
                )
            else:
                self.query_one("#progress_status", Label).update("[bold red]Failed[/bold red]")

        except Exception as e:
            self.query_one("#progress_status", Label).update(f"[bold red]Error: {e}[/bold red]")
            self.query_one("#log_output", Label).update(
                self.query_one("#log_output", Label).renderable +
                f"\n[red]{str(e)}[/red]"
            )
        finally:
            self.running = False
            self.query_one("#btn_run", Button).disabled = False
            self.query_one("#btn_stop", Button).disabled = True


class TUIProgressTracker(ProgressTracker):
    """Progress tracker that updates TUI widgets."""

    def __init__(self, screen: PipelineRunnerScreen):
        """Initialize the TUI progress tracker."""
        super().__init__()
        self.screen = screen
        self.current_step = None
        self.total_steps = 0
        self.completed_steps = 0

    def start_step(self, name: str, description: str = "") -> "TUIStepProgress":
        """Start a new step."""
        return TUIStepProgress(self.screen, name, description)


class TUIStepProgress:
    """Step progress for TUI."""

    def __init__(self, screen: PipelineRunnerScreen, name: str, description: str):
        """Initialize the step progress."""
        self.screen = screen
        self.name = name
        self.description = description

    def update(self, advance: int = 1, total: int | None = None):
        """Update progress (no-op for TUI)."""
        pass

    def complete(self, message: str = "Complete"):
        """Mark step as complete."""
        # Update log
        log = self.screen.query_one("#log_output", Label)
        current = log.renderable or ""
        log.update(f"{current}\n[green]✓[/green] [{self.name}] {message}")

    def error(self, message: str):
        """Report an error."""
        log = self.screen.query_one("#log_output", Label)
        current = log.renderable or ""
        log.update(f"{current}\n[red]✗[/red] [{self.name}] {message}")
