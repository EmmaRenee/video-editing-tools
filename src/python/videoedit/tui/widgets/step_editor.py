"""
Step editor widget - Edit operation parameters in a modal dialog.

Provides a modal interface for editing individual step parameters
when building a pipeline.
"""
from textual.screen import ModalScreen
from textual.widgets import (
    Input, Label, Button, Checkbox, Select
)
from textual.containers import Vertical, Horizontal
from textual import on
from textual import events


class StepEditorScreen(ModalScreen):
    """Modal screen for editing step parameters."""

    DEFAULT_CSS = """
    StepEditorScreen {
        align: center middle;
    }

    #dialog {
        width: 60%;
        height: auto;
        max-height: 70%;
        border: thick $primary;
        background: $panel;
        padding: 2;
    }

    #title {
        text-style: bold;
        text-align: center;
        margin: 0 0 2 0;
        color: $primary;
        text-size: 150%;
    }

    #param_container {
        height: auto;
        max-height: 40;
        overflow-y: auto;
    }

    .param_row {
        margin: 1 0;
    }

    .param_label {
        text-style: bold;
        color: $accent;
    }

    .param_input {
        width: 1fr;
    }

    #actions {
        margin: 2 0 0 0;
        height: 3;
    }

    #actions Button {
        margin: 0 1 0 0;
    }

    Checkbox {
        margin: 1 0;
    }
    """

    def __init__(self, step, operation_key: str, step_idx: int, operation_info: dict):
        """Initialize the step editor.

        Args:
            step: The pipeline step being edited
            operation_key: The operation identifier (e.g., "transcribe_whisper")
            step_idx: Index of the step in the pipeline
            operation_info: Dict containing operation metadata including params config
        """
        super().__init__()
        self.step = step
        self.operation_key = operation_key
        self.step_idx = step_idx
        self.operation_info = operation_info
        self.param_widgets = {}  # Store references to param widgets

    def compose(self):
        """Compose the modal dialog."""
        with Vertical(id="dialog"):
            yield Label(f"Edit: {self.step.name}", id="title")

            with Vertical(id="param_container"):
                params = self.operation_info.get("params", {})

                if not params:
                    yield Label("[dim]No parameters for this operation[/dim]")
                else:
                    for param_name, param_config in params.items():
                        param_label = param_name.replace("_", " ").title()
                        current_value = self.step.params.get(param_name)

                        yield Label(param_label, classes="param_label")

                        param_type = param_config.get("type")

                        if param_type == "select":
                            options = [
                                (str(opt), str(opt))
                                for opt in param_config.get("options", [])
                            ]
                            default = param_config.get("default")
                            selected = str(current_value) if current_value is not None else str(default)

                            select = Select(
                                options,
                                value=selected,
                                id=f"param_{param_name}"
                            )
                            self.param_widgets[param_name] = ("select", select)
                            yield select

                        elif param_type == "boolean":
                            checkbox = Checkbox(
                                value=current_value if current_value is not None else param_config.get("default", False),
                                id=f"param_{param_name}"
                            )
                            self.param_widgets[param_name] = ("boolean", checkbox)
                            yield checkbox

                        elif param_type == "number":
                            default = param_config.get("default", "")
                            value = str(current_value) if current_value is not None else str(default)
                            inp = Input(
                                value=value,
                                placeholder=str(default),
                                id=f"param_{param_name}",
                                type="number"
                            )
                            self.param_widgets[param_name] = ("number", inp)
                            yield inp

                        else:  # text or string
                            default = param_config.get("default", "")
                            value = str(current_value) if current_value is not None else str(default)
                            inp = Input(
                                value=value,
                                placeholder=default,
                                id=f"param_{param_name}"
                            )
                            self.param_widgets[param_name] = ("text", inp)
                            yield inp

            with Horizontal(id="actions"):
                yield Button("Save", id="btn_save", variant="primary")
                yield Button("Cancel", id="btn_cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "btn_save":
            self._save_params()
            self.dismiss({"action": "save", "step_idx": self.step_idx, "params": self.step.params})
        elif event.button.id == "btn_cancel":
            self.dismiss({"action": "cancel"})

    def _save_params(self):
        """Save parameters from widgets back to the step."""
        for param_name, (param_type, widget) in self.param_widgets.items():
            if param_type == "select":
                self.step.params[param_name] = widget.value
            elif param_type == "boolean":
                self.step.params[param_name] = widget.value
            elif param_type == "number":
                val = widget.value
                try:
                    self.step.params[param_name] = float(val) if "." in val else int(val)
                except ValueError:
                    self.step.params[param_name] = val
            else:  # text
                self.step.params[param_name] = widget.value
